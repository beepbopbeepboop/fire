#!/usr/bin/env python3
"""Monomorphization engine — MODULE_CACHE_DESIGN.md stage 5.

A generic is not one symbol; each instantiation is. When a client uses
`Generic[ConcreteType]`, we compute a content key over (template identity,
concrete type args, comptime params), look it up in the shared CAS, and on a
miss instantiate → compile → publish. Instantiate once, ever: the next client or
build faults the instantiation in. This is the "compile cost = sum of *unique*
instantiations, not TU × instantiations" property — the thing C++ gets wrong.

The substitution here is intentionally simple (textual over a single-`fn`
template) — enough to prove the keying + cache mechanism end to end. The real
engine is AST-driven and hooks the existing whole-program analysis in
`DispatchSolver` (gimple_codegen.py); the *cache contract* it relies on is this
module's `instantiate()`.
"""
import os
import re
import tempfile
import subprocess

import cas
from build_config import find_gcc, find_gxx
from gimple_codegen import GimpleGen
from fire_compiler import py_tokenize, Parser

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')
_OBJ_FLAGS = ('-fgimple', '-fPIC', f'-I{RUNTIME}')
_CPP_FLAGS = ('-std=c++20', '-fPIC', f'-I{RUNTIME}')

# The head of a generic definition, up to and INCLUDING its opening bracket.
# The parameter list itself is found by COUNTING brackets (`head_match`), not by
# a `[^\]]*` character class: a parameter whose declared type is itself a type
# application — `keys: List[T]`, `width: SIMD[dtype, width]`, `*values: Trait`
# beside a `List[T]` — puts a `]` inside the parameter list, and a class that
# stops at the first `]` ends the match there. That is not a rare shape, it is
# `std/collections/type_dict.mojo` (the whole API is compile-time and every
# parameter is a value) and every numeric template the compiled path
# instantiates, and the failure it produced was an EMITTED FILE THAT DOES NOT
# PARSE: `monomorphize_source` cut the head at `m.end()` and left `]:` behind,
# so `struct Box[T, keys: List[T]]:` became
# `struct Box_1_T_3_Int_4_keys_39__x005B1_x002C_…_x005D]:` and the build died
# at `Unexpected RBRACKET(']')` on both backends. See
# `the variadic bracket arity and the `len(<display>)` fold (landed in e72a5f93)` §0a, where
# the before/after table and the stdlib file that reaches it are.
_HEAD = re.compile(r'\b(fn|def|struct)\s+(\w+)\s*\[')


class _HeadMatch:
    """The `(kind, name, params)` head of a generic definition.

    Quacks like the `re.Match` the five call sites were written against —
    `group(1)`/`group(2)`, `start()`, `end()` — so `monomorphize_source` and
    `elaborate.py`'s readers are unchanged, and `params` carries the text
    INSIDE the brackets, which is what they actually all wanted from `group(2)`.

    `end()` is one past the MATCHING `]`, which is the offset
    `monomorphize_source` cuts the source at and `_code_only` blanks out.
    """

    __slots__ = ("kind", "name", "params", "_start", "_end")

    def __init__(self, kind, name, params, start, end):
        self.kind = kind
        self.name = name
        self.params = params
        self._start = start
        self._end = end

    def group(self, n):
        return {1: self.kind, 2: self.name, 3: self.params}[n]

    def start(self):
        return self._start

    def end(self):
        return self._end

    def __repr__(self):
        return (f"<head {self.kind} {self.name}[{self.params}] "
                f"{self._start}..{self._end}>")


def head_match(src: str, kinds: str = r'(?:fn|def|struct)'):
    """The first generic definition head in `src`, brackets balanced, or None.

    **Balanced, and that is the whole point.** `fn Box[T: AnyType, keys:
    List[T]]` has a `]` at `List[T]`'s, and a pattern that stops at the first
    `]` reports the parameter list as `T: AnyType, keys: List[T` — which is
    wrong in the two ways that matter at once: `monomorphize_source` cuts the
    head there and emits a definition with a stray `]` (a file that does not
    parse), and every reader of the parameter list downstream reads a
    truncated one (`keys: List[T` with no closing bracket).

    `kinds` narrows to `(?:fn|def)` for a function template; the compiled
    path's struct-only readers pass `(?:struct)`. A regex that finds the head
    and a scan that finds its END are two steps because the end is not a
    regular-language property of the text — it is a nesting depth — and the
    scan is four lines.

    **An unbalanced head keeps the OLD answer** rather than raising: a `fn`
    whose brackets never close is malformed source, and the previous behaviour
    for it was a truncated match whose consequence was a parse error downstream.
    Inventing a refusal here would change which layer reports the malformation,
    and this function's job is to find the head, not to judge the source.
    """
    m = re.compile(r'\b(' + kinds + r')\s+(\w+)\s*\[').search(src)
    if not m:
        return None
    depth = 0
    for i in range(m.end() - 1, len(src)):
        c = src[i]
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                return _HeadMatch(m.group(1), m.group(2), src[m.end():i],
                                  m.start(), i + 1)
    close = src.find(']', m.end() - 1)
    if close < 0:                       # no `]` at all: nothing to cut to
        return _HeadMatch(m.group(1), m.group(2), src[m.end():], m.start(),
                          m.end())
    return _HeadMatch(m.group(1), m.group(2), src[m.end():close], m.start(),
                      close + 1)


_ALNUM = re.compile(r'[A-Za-z0-9]')


def safe_suffix(s: str) -> str:
    """Encode a type-arg string into a valid C identifier fragment, INJECTIVELY.

    Parametric args like `List[Int]` contain `[`/`]`/`,`/spaces, which are
    illegal in a C symbol, so every non-[A-Za-z0-9] char has to be escaped
    (review finding #4). The previous implementation mapped each of them to
    `_`, which is LOSSY and therefore not an encoding at all: `List[Int]`,
    `List_Int`, `A B`, `A.B` and `A_B` all produced the same fragment, so two
    different instantiations of one template could be given one C symbol.
    Measured over 1752 generated (name, type_args) pairs: 1512 collided.

    The escape is `_x` + 4 uppercase hex digits (or `_X` + 8, for a code point
    outside the BMP). Uppercase hex is deliberate, not cosmetic: it makes an
    escape impossible to confuse with `mojo/middle/types.py::demangle_overload`'s
    `___([0-9a-f]{6})$` overload-hash tail, which a lowercase `_x0011` could in
    principle grow into. The code is injective because `_` is itself escaped and
    never appears literally, so decoding is a unique left-to-right scan: on `_`,
    the next char says the width (`x` = 4 digits, `X` = 8) and the digits after
    it are the code point.

    `_` is escaped too, so a type argument containing one cannot manufacture a
    separator: every structural character in a mangled name is emitted by
    `_fields`, never by `safe_suffix`."""
    out = []
    for ch in s:
        if _ALNUM.match(ch):
            out.append(ch)
        else:
            c = ord(ch)
            out.append(f'_x{c:04X}' if c < 0x10000 else f'_X{c:08X}')
    return ''.join(out)


def _fields(pairs) -> str:
    """Length-prefixed concatenation of (name, value) pairs — injective on the
    ordered sequence.

    Each component is `{len(key)}_{key}_{len(value)}_{value}`, so both the
    key/value boundary and the component/component boundary are fixed by a
    count rather than by a separator character that a value could itself
    contain. The old scheme joined the VALUES under `_` with no keys at all,
    which is what made `mangle('Box', {'T': 'A_B'})` and
    `mangle('Box', {'T': 'A', 'o': 'B'})` the same string — two different
    instantiations, one symbol. Keying on the parameter NAME as well as its
    value also separates two templates that share a base name and differ only
    in what they call their parameter (`struct Foo[T]` vs `struct Foo[U]`),
    which a value-only key cannot.

    Decodable left to right, uniquely: the maximal digit run is a count, the
    next `_` separates, and each count is followed by exactly that many
    characters."""
    out = []
    for k, v in pairs:
        ks, vs = safe_suffix(str(k)), safe_suffix(str(v))
        out.append(f'{len(ks)}_{ks}_{len(vs)}_{vs}')
    return '_'.join(out)


def mangle(name: str, type_args: dict) -> str:
    """Stable, INJECTIVE monomorphized symbol name.

    `mangle(box, {T: Int64})` is now `box_1_T_5_Int64`, not `box_Int64`. The
    bytes change for every existing instantiation, deliberately: the old scheme
    was not injective, so the name was not a function of the instantiation, and
    the CAS key (`cas.instantiation_key`) folds in `compiler_fingerprint()`,
    which hashes this file — every previously cached object is therefore
    unreachable rather than silently served under the new spelling. See
    `bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md`.

    A name with no type arguments is returned unchanged, so a template's
    zero-parameter instantiation keeps its own name (`empty` -> `empty`)."""
    if not type_args:
        return name
    return f"{name}_{_fields((k, type_args[k]) for k in sorted(type_args))}"


def mangle_signature(name: str, parts) -> str:
    """Injective symbol for an overload of `name` selected by its parameter
    types (the `elaborate.Elaborator.elaborate_overload_call` route). Same
    encoding as `mangle`, keyed by positional index, so two overloads whose
    parameter types differ only in segmentation cannot share a symbol — the
    same defect `mangle` had."""
    parts = list(parts)
    return f"{name}__{_fields(enumerate(parts))}" if parts else f"{name}__void"


def _check_no_value_shadow(src: str, type_params) -> None:
    """Raise if a type parameter is also used as a *binding name* (a `var`/`for`
    target or an assignment target). Textual substitution would then rewrite that
    value identifier to a type name — a silent miscompile (review finding #3). A
    type used as a constructor (`T()`) or in a type position is fine; only bindings
    are unsafe, and bindings shadowing a type parameter are pathological, so we
    fail loudly rather than emit wrong code."""
    for tp in type_params:
        e = re.escape(tp)
        # The `var`/`for` match must not be a MEMBER ACCESS: the function
        # type parameter's owned-parameter convention (`def(var
        # InnerIteratorType.Element) thin -> OutputType` in std/iter's
        # _MapIterator, measured 2026-10-21 (further)) spells `var
        # <Type>.Element` in an ANNOTATION — a type position, not a binding —
        # and the bare-word substitution rewrites it to `var
        # <inner>.Element`, which is exactly what the substituted annotation
        # should read. A real statement-level `var T` / `for T` is followed
        # by `=`, `in`, or end-of-line, never `.`.
        if re.search(rf'\b(?:var|for)\s+{e}\b(?!\s*\.)', src) or \
           re.search(rf'(?m)^\s*{e}\s*=(?!=)', src):
            raise ValueError(
                f"monomorphize: type parameter {tp!r} is used as a value/binding "
                f"name; cannot textually instantiate this template")


def _shadowed_spans(src: str, tp: str) -> list:
    """[start, end) char spans of any NESTED `fn`/`def NAME[...]` inside
    `src` whose OWN bracket-parameter list re-declares `tp` as one of ITS
    parameters — e.g. test_tracing.mojo's real shape: `def test_tracing
    [level, enabled]():` containing `async def test_tracing_add_two_of_them
    [enabled: Bool](...): ...`, itself containing `async def test_tracing_add
    [enabled: Bool, lhs: Int](...): ...` — THREE independent `enabled`
    bindings, only the outermost of which `monomorphize_source`'s caller is
    actually substituting.

    Blindly whole-word-substituting `tp` (e.g. `enabled` -> `True`)
    everywhere in `src`, as `monomorphize_source` did before this method
    existed, would rewrite a NESTED function's own bracket-parameter
    DECLARATION too (`[enabled: Bool, ...]` -> `[True: Bool, ...]`) — not a
    reference, a declaration -- producing flatly invalid Mojo syntax
    (`True` is not a legal parameter name), a real, hand-verified
    corruption risk this method exists to prevent (see bugs/CODEGEN_
    comptime_bracket_parametrized_function_calls_silently_wrong.md's
    test_tracing.mojo analysis, "monomorphizer substitutes level/enabled
    textually across the WHOLE extracted block — including inside test_
    tracing_add's own nested bracket declaration").

    Every span found here must be excluded from `tp`'s OUTER substitution
    (both the declaration AND the rest of that nested function's own body,
    where `tp` refers to the nested, independently-bound parameter, not the
    outer template's) — but is still exposed to substitution for any OTHER
    type param name that ISN'T shadowed there (`monomorphize_source` calls
    this once per type param, independently)."""
    spans = []
    e = re.escape(tp)
    # `async\s+` prefix optional: `async def NAME[...]` (a nested coroutine
    # with its own bracket params — test_tracing.mojo's real shape) is just
    # as much a re-declaration as a plain `def`/`fn`.
    for m in re.finditer(rf'(?m)^([ \t]*)(?:async\s+)?(?:fn|def)\s+\w+\s*\[[^\]]*\b{e}\b[^\]]*\]', src):
        indent = len(m.group(1))
        start = m.start()
        # End of this nested function: the first later line (blank lines
        # don't count) whose own indentation is <= this nested def's own
        # indentation — i.e. a dedent back to the enclosing scope or
        # beyond. No such line means the nested function runs to EOF.
        #
        # Searches the ORIGINAL `src` from `m.end()` via `Pattern.finditer`'s
        # own `pos` argument — NOT `src[m.end():]` (a fresh, sliced string).
        # `(?m)^` matches at an actual line start (position 0, or right
        # after a real `\n`) in whatever string it's matched against; a
        # slice starting mid-line (right after the declaration's own `]`,
        # e.g. still on the same line as `(a: Int, b: Int) -> Int:`) makes
        # ITS OWN start look like a false line-start to the regex engine,
        # which matched immediately there with indent=0 -- collapsing every
        # nested function's protected span down to just its own declaration
        # line and leaving its actual BODY (where the shadowed name is also
        # used, e.g. `test_tracing_add[enabled, 1](a)` inside `test_tracing
        # _add_two_of_them`'s body) still exposed to the outer substitution.
        # A hand-verified real bug caught by directly inspecting this
        # method's own span output against test_tracing.mojo's exact shape.
        end = len(src)
        _line_start_re = re.compile(r'(?m)^([ \t]*)\S')
        for lm in _line_start_re.finditer(src, m.end()):
            if len(lm.group(1)) <= indent:
                end = lm.start()
                break
        spans.append((start, end))
    return spans


def _sub_outside_spans(pattern: str, repl: str, src: str, spans: list) -> str:
    """`re.sub(pattern, repl, src)`, except inside `spans` (each an
    [start, end) char range, e.g. from `_shadowed_spans`) which are copied
    through untouched. `spans` need not be sorted or non-overlapping on
    entry (this method sorts and merges overlaps itself) — `_shadowed_spans`
    can return overlapping ranges for deeply-nested shadowing chains."""
    if not spans:
        return re.sub(pattern, repl, src)
    merged = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out = []
    pos = 0
    for s, e in merged:
        out.append(re.sub(pattern, repl, src[pos:s]))
        out.append(src[s:e])   # untouched: a nested, shadowed scope
        pos = e
    out.append(re.sub(pattern, repl, src[pos:]))
    return ''.join(out)


def _stmt_bracket_delta(line: str) -> int:
    """Net bracket balance of one physical line, ignoring string literals and
    `#` comments.

    `_sub_variadic`'s statement neutralizer (pass 7) needs to know where a
    multi-line statement ENDS: a `comptime assert` whose expression or
    message is parenthesized, or an `__mlir_op` call with a broken argument
    list, opens brackets on its first line and closes them on a later one —
    the cumulative balance reaches zero exactly on the statement's last
    line. Ignoring strings is load-bearing, not hygiene: an assert message
    may itself carry brackets (`"Length of Coord ("`) and a backtick MLIR-op
    name may carry a bracketed argument (`__mlir_op.`index.cmp`[pred=...]`)
    — counting those would end the statement one or two lines past its real
    end and swallow live code. Triple-quoted docstrings are treated as plain
    string runs: a neutralized statement never spans one, so an unterminated
    run just contributes no balance for the rest of the line."""
    d = 0
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c in '\'"':
            q = line[i:i + 3] if line[i:i + 3] in ('"""', "'''") else c
            i += len(q)
            while i < n:
                if len(q) == 1 and line[i] == '\\':
                    i += 2
                    continue
                if line[i:i + len(q)] == q:
                    i += len(q)
                    break
                i += 1
            continue
        if c == '`':
            i += 1
            while i < n and line[i] != '`':
                i += 1
            i += 1
            continue
        if c == '#':
            return d
        if c in '([{':
            d += 1
        elif c in ')]}':
            d -= 1
        i += 1
    return d


def _sub_variadic(src: str, tp: str, items: list, element_map: dict = None,
                  self_element: str = None) -> str:
    """Substitute a VARIADIC type parameter (`*Ts`, measured 2026-10-21,
    part 4: `_ChainedIterator[*Ts: Iterator]` / `_ZipIterator[origin, *Ts]`,
    the `chain`/`zip` out-parameter factories' wrappers) for a LIST of
    concrete inner types.

    The body spells the parameter WITHOUT the star (`Self.Ts`), so the
    plain `Self.<param>` / bare-word passes (keyed on `*Ts`) never touch
    it — and a bare `Ts -> a, b` rewrite would corrupt every context
    (`Self.Ts[0].Element` -> `Self.a, b[0].Element`). The measured forms
    in the two wrapper families, each handled in turn:

    1. `*Self.Ts` / `*Ts` — the variadic UNPACK inside a bracket list
       (`Tuple[*Self.Ts]`, the where-clause `conforms_to(Tuple[*Ts], ...)`)
       -> the comma-joined inners.
    2. `Self.Ts[0]` / `Ts[0]` — INDEXED access on the inners tuple
       (`comptime Element = Self.Ts[0].Element`) -> the N-th inner.
    3. the zip `Element` expression — `Tuple[*TypeList[Trait=Iterator,
       Self.Ts.values]().map[Self._mapper]()]` where `_mapper[T] = T.
       Element` — the ELEMENTS of the inners, as the unpacked list.
    4. `comptime for <i> in range(Self.<M>.__len__()):` where `<M>` is a
       comptime member `= Tuple[*Self.Ts]` (after pass 1 its RHS is the
       concrete inners) — UNROLLED: the loop variable is a compile-time
       index into a FIXED FIELD tuple (the C representation is a struct
       with one field per inner — a runtime index has no lowering), so the
       header is replaced by N copies of the body with `<i>` bound to the
       literal 0..N-1 at the body's own indentation.
    5. `Self.<M>` — the remaining comptime-MEMBER references in TYPE
       positions (`var _iterators: Self._Iterators`, `-> Self.Element`)
       -> the member's (already-substituted) RHS.
    6. `<inner>.Element` -> that inner's ELEMENT mention, from
       `element_map` (the out-res seed knows each inner's element: the
       first container's element for `Self.Element = Self.Ts[0].Element`).

    Refusal, not guessing: an unrolled comptime-for whose range argument is
    not the measured `<Self.<M>.__len__()` shape, or a `Self.<M>` reference
    to a member with no single-line `comptime <M> = <RHS>` definition, is
    raised as ValueError — the caller (`_materialize`) turns that into a
    named refusal, the standard discipline for this area."""
    bare = tp[1:]
    join = ', '.join(items)
    # 1a. the unpack as a VARIADIC PARAMETER ANNOTATION (`*args: *Self.
    # element_types`): a parameter annotation is ONE type — the parser
    # reads exactly one `_parse_type_ann()` for it — so the comma-joined
    # list is wrong there in the one way a list is never wrong inside a
    # bracket argument list (`Tuple[*Self.element_types]` DOES want every
    # inner). The join left the SECOND inner as a spurious next-parameter
    # name, and an inner with its own bracket arguments (`ComptimeInt[3]`)
    # had its `[3]` skipped as a LIFETIME bracket, dropping the list's
    # COMMA — or, for the last inner, the parameter list's RPAREN — onto
    # the parameter-NAME position: `SyntaxError: 147:71: Expected NAME or
    # KW got COMMA` for `Coord[ComptimeInt[5], Int32, ComptimeInt[3],
    # Int64]` and `147:53: ... got RPAREN` for `Coord[Int,
    # ComptimeInt[1]]` (coord.mojo:323's `def __init__(out self, var
    # *args: *Self.element_types)`, emitted line 147 — the first
    # MULTI-inner variadic PARAMETER the stdlib has: every measured
    # wrapper spelled its inners in a bracket list, where the full join
    # is the right answer, so pass 1's two regexes never saw this
    # context). The `: *` prefix is the marker: an unpack whose text
    # immediately precedes a colon-and-star is a parameter annotation,
    # and the only legal Mojo unpack in an annotation position is the
    # variadic parameter's own. The annotation's text is otherwise inert
    # for the artifact — the TU's C signature for the `*args` slot comes
    # from `_signature_ctypes`' own `startswith('*')` branch (the packing
    # sentinel / `MojoList *`), never from the annotation — so the FIRST
    # inner is the honest single-type spelling (the wrapper families'
    # element convention is `Self.Ts[0]`; a one-inner instantiation
    # already degenerates `join` to exactly this text, byte for byte).
    src = re.sub(rf':\s*\*\s*Self\.{re.escape(bare)}\b', f': {items[0]}', src)
    src = re.sub(rf':\s*\*\s*(?<![\w.])' + re.escape(bare) + r'\b',
                 f': {items[0]}', src)
    # 1. the unpack
    src = re.sub(rf'\*\s*Self\.{re.escape(bare)}\b', join, src)
    src = re.sub(rf'\*\s*(?<![\w.])' + re.escape(bare) + r'\b', join, src)

    def _idx(m):
        k = int(m.group(1))
        if k >= len(items):
            raise ValueError(
                f'variadic {tp!r}: index {k} beyond its {len(items)} bindings')
        return items[k]

    # 2. the indexed access
    src = re.sub(rf'Self\.{re.escape(bare)}\[(\d+)\]',
                 lambda m: _idx(m), src)
    src = re.sub(rf'(?<![\w.]){re.escape(bare)}\[(\d+)\]',
                 lambda m: _idx(m), src)

    # 3. the zip Element expression (the TypeList over the inners, mapped
    # through the wrapper's own `_mapper` = `.Element`): `*TypeList[...]`
    # is the UNPACK of the element list — the leading star is consumed
    # (it is the unpack, not a pointer — `*Self.Ts` in pass 1 is the same
    # idiom in the inners position)
    src = re.sub(
        r'\*?\s*TypeList\[Trait=Iterator,\s*Self\.' + re.escape(bare) +
        r'\.values\]\(\)\.map\[Self\._mapper\]\(\)',
        ', '.join(f'{it}.Element' for it in items), src)

    # 4. the comptime-for unroll (before member expansion: the range
    # argument names the member, the body references the loop variable).
    # The body is captured by INDENT SCAN, not one greedy regex: the loop
    # body may CONTAIN sibling statements of the enclosing block (zip's
    # `__next__` nests its second comptime-for inside the try/except whose
    # OUTLINE sits at the same indent as the first loop's body), and a
    # `.*\n`-per-line capture swallows those, duplicating the whole
    # except-clause into every copy.
    members = dict(re.findall(
        r'comptime (\w+) = ([^\n]+)', src))
    lines = src.splitlines(keepends=True)
    out = []
    _i = 0
    _hdr_re = re.compile(
        r'^([ \t]*)comptime for (\w+) in range\(Self\.(\w+)\.__len__\(\)\):[ \t]*$')
    while _i < len(lines):
        m = _hdr_re.match(lines[_i])
        if not m:
            out.append(lines[_i])
            _i += 1
            continue
        _ind = len(m.group(1))
        var, member = m.group(2), m.group(3)
        rhs = members.get(member)
        if rhs is None or not re.match(r'Tuple\[', rhs.strip()):
            raise ValueError(
                f'variadic {tp!r}: comptime-for over {member}.__len__() '
                'whose member is not a single-line Tuple[...] definition')
        # TOP-LEVEL element count of the unpacked member RHS (after pass 1
        # it is the comma-joined concrete inners): a naive `split(',')`
        # miscounts when an inner's own bracket arguments carry commas —
        # measured 2026-10-22, gimplerunner `zip([0, 1], [2, 3])`: the
        # borrowed inners are `_ListIter[False, Int, ImmOrigin, True]`
        # (three nested commas each), so two inners read as eight and the
        # unroll refused, while the stdlib files' 1-argument owned inners
        # (`_ListIterOwned[String]`) read correctly and the 610 sweep never
        # saw the shape.
        _inner = rhs.strip()
        if _inner.startswith('Tuple['):
            _inner = _inner[len('Tuple['):]
        _inner = _inner.strip()
        while _inner.endswith(']'):
            _inner = _inner[:-1].rstrip()
        n, _depth = (1 if _inner.strip() else 0), 0
        for _ch in _inner:
            if _ch in '[(':
                _depth += 1
            elif _ch in '])':
                _depth -= 1
            elif _ch == ',' and _depth == 0:
                n += 1
        if n != len(items):
            raise ValueError(
                f'variadic {tp!r}: {member} has {n} elements, the call '
                f'binds {len(items)}')
        # Body: the run of lines indented STRICTLY deeper than the header
        # (blank lines ride along; the run ends at the first line whose
        # indent is back at or above the header's).
        body_lines = []
        _j = _i + 1
        while _j < len(lines):
            _ln = lines[_j].rstrip('\n')
            if _ln.strip() == '':
                body_lines.append(lines[_j])
                _j += 1
                continue
            if len(_ln) - len(_ln.lstrip(' ')) <= _ind:
                break
            body_lines.append(lines[_j])
            _j += 1
        while body_lines and body_lines[-1].strip() == '':
            body_lines.pop()
        # Every copy keeps the header's indentation level: the loop BODY
        # sat one level deeper than the header, and with the header gone
        # the copies take the header's place — the body text is de-
        # indented by that one level (its first statement's indent minus
        # the header's). A `continue` left behind by the unroll has no
        # loop to continue: the measured spelling (chain `bounds()`'s
        # `if self._idx > i: continue`, the guard at the SAME indent as
        # the rest of the body) means "SKIP this copy's rest when the
        # condition holds" — so the copy becomes `if not (<cond>):` +
        # the rest of the copy indented one level UNDER the guard.
        # Anything a `continue` could mean that this shape does not
        # cover is a refusal, not a guess.
        _body = ''.join(body_lines)
        _delta = 0
        for _b0 in body_lines:
            if _b0.strip():
                _delta = len(_b0) - len(_b0.lstrip(' ')) - _ind
                break
        if _delta > 0:
            _body = '\n'.join(
                _b[_delta:] if _b.strip() else _b
                for _b in body_lines) + ('\n' if body_lines and
                                         body_lines[-1].endswith('\n') else '')
        for _k in range(n):
            _c = re.sub(rf'(?<![\w.]){re.escape(var)}\b', str(_k), _body)
            _cl = _c.splitlines(keepends=True)
            # bottom-up: an outer transform's +4 must land on top of an
            # inner one already applied (nested guards nest correctly)
            for _li in [i for i, ln in enumerate(_cl)
                        if re.match(r'^[ \t]*continue[ \t]*$', ln)][::-1]:
                _ci = len(_cl[_li]) - len(_cl[_li].lstrip(' '))
                _dj = _li - 1
                _found = None
                while _dj >= 0:
                    _dl = _cl[_dj].rstrip('\n')
                    if _dl.strip() == '':
                        _dj -= 1
                        continue
                    _di = len(_dl) - len(_dl.lstrip(' '))
                    if _di <= _ci:
                        _mm = re.match(
                            r'^[ \t]*if ([^\n:]+):[ \t]*$', _cl[_dj])
                        if _mm:
                            _found = _dj
                    break
                if _found is None:
                    raise ValueError(
                        f'variadic {tp!r}: the unrolled body carries a '
                        '`continue` whose nearest non-deeper statement '
                        'is not an `if` guard')
                _cl[_found] = re.sub(
                    r'if ([^\n:]+):$', r'if not (\1):', _cl[_found])
                del _cl[_li]
                for _j2 in range(_li, len(_cl)):
                    if _cl[_j2].strip():
                        _cl[_j2] = '    ' + _cl[_j2]
            out.append(''.join(_cl))
        _i = _j
    src = ''.join(out)

    # 5. the remaining comptime-member references in type positions.
    # GATED on the RHS being a balanced, single-line, type-like mention:
    # the zip `Element` definition spans LINES (`Tuple[\n ... \n]`), and
    # the single-line capture would splice a dangling `Tuple[` into every
    # `Self.Element` use — a broken signature, not a substitution. An
    # unbalanced RHS is left for the `self_element` override (the out-res
    # seed computes the element mention explicitly) or for the honest
    # int64_t erasure, never a corrupted signature.
    if self_element is not None:
        src = re.sub(r'\bSelf\.Element\b', self_element, src)
    for mn, rhs in members.items():
        r = rhs.strip()
        if not re.match(r'^[A-Za-z_][\w .*,\[\]()\-]*$', r) or \
                r.count('[') != r.count(']'):
            continue
        src = re.sub(rf'\bSelf\.{re.escape(mn)}\b', r, src)

    # 6. the inner -> element mentions
    if element_map:
        for it, elem in element_map.items():
            src = re.sub(rf'\b{re.escape(it)}\.Element\b', elem, src)

    # 7. the unsafe-write / mlir-op / rebind / forget splices — the zip
    # `__next__`'s measured spelling after the unroll above — to the
    # lowerable forms: a plain subscript assignment (the tuple field's
    # constant-index lowering), a `pass` where the runtime action is a
    # no-op in this C representation (a by-value word/pointer slot has
    # nothing to deinit; the in-TU protocol's documented leak class), the
    # identity for `rebind_var[T](x)`, and a comment-out for the raw-MLIR
    # op and the `std.memory` forget (no lowering, nothing to do for a
    # by-value tuple local).
    def _unwrite(m):
        # the two indices are the same loop variable (the unroll bound
        # both to the same literal); if a future spelling disagrees,
        # leave the text for the honest downstream refusal
        if m.group(1) != m.group(2):
            return m.group(0)
        return f'res[{m.group(1)}] = next(self._values[{m.group(1)}])'

    src = re.sub(
        r'Pointer\(to=res\[(\d+)\]\)\.unsafe_write\(\s*'
        r'rebind_var\[type_of\(res\[\1\]\)\]\('
        r'next\(self\._values\[(\d+)\]\)\)\s*\)',
        _unwrite, src, flags=re.S)
    src = re.sub(r'Pointer\(to=res\[\d+\]\)\.unsafe_deinit_pointee\(\)',
                 'pass', src)
    src = re.sub(r'rebind_var\[[^\]]*\]\(((?:[^()]|\([^()]*\))*)\)', r'\1',
                 src)

    # The three statement neutralizers must replace the WHOLE logical
    # statement, not its first physical line. `[^\n]*$` stops at the end of
    # the line, so a statement broken across lines (a call with a broken
    # argument list, a `comptime assert` whose expression or message is
    # parenthesized) had only its first line turned into `pass`, and its
    # continuation lines were left in place — indented deeper than the block
    # the new `pass` closes, so the emitted file died at the first of them
    # with `SyntaxError: Unexpected INDENT('')`. Measured 2026-10-26 on the
    # four variadic stdlib generics: `Coord.__eq__`'s
    # `comptime assert Self.__len__() == Coord[*other_types].__len__(), ( ... )`
    # (coord.mojo:419 → failed at emitted line 244), `_RegTuple.__init__`'s
    # `__mlir_op.`lit.ownership.mark_initialized`( ... )` (coord.mojo:1606
    # → line 25), `UnsafeUnion.__init__`'s `comptime assert Self._is_element[
    # T ]()` (unsafe_union.mojo:194 → line 111) and `Variant._check`'s
    # `comptime assert ( ... ), "Type does not exist in Variant."`
    # (variant.mojo:560 → line 136). The statement ends on the line whose
    # cumulative bracket balance (strings/comments ignored — see
    # `_stmt_bracket_delta`) returns to zero; a balance that reaches EOF
    # without closing is malformed, refused rather than half-neutralized.
    # Single-line statements keep the old byte-for-byte output (same pad,
    # same `pass`, same trailing newline).
    _stmt_res = [
        re.compile(p)
        for p in (r'^[ \t]*__mlir_op\.[^\n]*$',
                  r'^[ \t]*std\.memory\.forget_deinit\([^\n]*$',
                  r'^[ \t]*comptime assert [^\n]*$')
    ]
    lines = src.splitlines(keepends=True)
    out = []
    _i = 0
    while _i < len(lines):
        _ln = lines[_i]
        _m = None
        for _r in _stmt_res:
            _m = _r.match(_ln)
            if _m:
                break
        if _m is None:
            out.append(_ln)
            _i += 1
            continue
        _pad = _ln[:len(_ln) - len(_ln.lstrip())]
        _depth, _j = 0, _i
        while True:
            _depth += _stmt_bracket_delta(lines[_j])
            if _depth <= 0:
                break
            _j += 1
            if _j >= len(lines):
                raise ValueError(
                    f'variadic {tp!r}: the statement at line {_i + 1} opens '
                    'brackets that never close; refusing to neutralize it')
        _last = lines[_j]
        out.append(_pad + 'pass' + ('\n' if _last.endswith('\n') else ''))
        _i = _j + 1
    src = ''.join(out)
    return src


def monomorphize_source(template_src: str, type_args: dict,
                        element_map: dict = None,
                        self_element: str = None) -> tuple:
    """Specialize a single `fn` OR `struct` generic template for concrete type
    args. Returns (mangled_name, concrete_source). Textual substitution: drop the
    `[params]` block, rename the definition, and replace each type-param
    identifier with its concrete type as a whole word — except inside a
    NESTED function that re-declares (shadows) that same type-param name as
    its own independent bracket parameter (see `_shadowed_spans`).

    `Self.<param>` is substituted as a UNIT, in a pass of its own that runs
    BEFORE the bare-word one, so the `Self.` qualifier is dropped along with
    the name it qualifies. `Self.T` inside `struct Box[T]` is the enclosing
    type's own name for the parameter `T`, so for the instantiation
    `Box[int64_t]` it denotes exactly `int64_t`; the bare-word pass alone
    could only rewrite its `T` and leave the `Self.` glued to the argument,
    producing `Self.int64_t` — a member name that means nothing, which
    `_mojo_type` then silently answered as `int64_t`. That silence is what
    made the whole `next(<user-defined iterator struct>)` family a declared
    red: stdlib's `_PeekableIterator[InnerIterator]` declares
    `var _inner: Self.InnerIterator` and `std/itertools`' iterators declare
    `var _inner: Self.InnerIteratorType`, so the monomorphized struct's field
    was boxed `int64_t` instead of `<iterator> *`, the receiver of
    `next(self._inner)` / `next(it)` had no resolvable struct type, and the
    `for`-loop over the same object degraded to `mojo_unsupported_iter`
    (see CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered).
    Substituting the qualified form first also keeps the bare pass from
    double-substituting it — by then no `Self.<param>` text survives."""

    # CONSTANT FOLDING (part 4, measured 2026-10-21): the spliced wrapper
    # bodies reference `Int.MAX` (`_ZipIterator.bounds`: `var res_lower =
    # Int.MAX` / `res_upper.or_else(Int.MAX)`; `_ChainedIterator.bounds`:
    # `Int.MAX - final_lb`). In real Mojo those are COMPILE-TIME constants;
    # this codegen's class-ref fallback instead boxes the class as a NULL
    # object and dispatches a runtime getattr on it —
    # `_mojo_dispatch_getattr(0, "MAX")` — and the runtime has no class-
    # attribute table, so it raises `AttributeError: MAX` (measured on the
    # `test_zip_bounds` ladder: `Unhandled exception: AttributeError:
    # MAX`). The spliced bodies are new code emitted only by this path, so
    # folding the measured constant to its definitional literal here
    # (`Int.MAX` is 2**63-1) keeps the fix inside the out-res subpath —
    # the emitted C of every non-spliced file is untouched (their
    # `Int.MAX` still takes the class-ref path, byte-identical to a clean
    # master). `(?<![\w.])` keeps `UInt.MAX` (should one ever appear) out
    # of scope: a bare `str.replace` would corrupt it into
    # `U9223372036854775807`.
    template_src = re.sub(
        r'(?<![\w.])Int\.MAX\b', '9223372036854775807', template_src)

    # CONSTANT FOLDING (part 6, measured 2026-10-22, family C): the spliced
    # `_Product2.bounds` (std/itertools/itertools.mojo:169 — the ONE
    # `not X[1]` in the stdlib; `_Product3`/`_Product4.bounds` delegate to
    # an inner `_Product2`) guards the upper-bound formula with
    # `if not a_bounds[1] or not initial_b_bounds[1]` — a None-ness test on
    # the `Optional[Int]` slot 1 of the `*_bounds` tuples. This backend has
    # no value-level Optional representation: slot 1 flows as a raw int64
    # word through the runtime tuple, so the guard lowers to `word == 0` and
    # misreads an exhausted iterator's Some(0) count as None (measured on
    # the `test_product_bounds` ladder: at i=1 the a-iterator is exhausted,
    # a_bounds[1] = Some(0) = word 0, the guard fires, bounds() returns
    # (lower, None), and the test's `bounds()[1].value()` reads 0 where 1 is
    # expected — the exact emitted C: `_t23 = mojo_list_get_int (a_bounds,
    # 1); _t24 = _t23 == 0LL;`).
    #
    # The guard is dead for every measured instantiation: both `*_bounds`
    # values come from `_ListIter.bounds` (the product instantiations in the
    # sweep take List/Range/CopyableOwnedIter args, all list iterators),
    # which wraps a non-negative count in slot 1 UNCONDITIONALLY (`return
    # (iter_len, {iter_len})`) — it never emits a None there, so `not
    # Some(count)` is a compile-time false. Fold the guard to `if False:`
    # (the upper formula then runs unconditionally and is value-correct:
    # slot-1 words are the counts, and `or_else(0)` under this codegen's
    # None=0 word encoding is the identity — exactly or_else(0)).
    #
    # NOT a sentinel: INT64_MIN is not expressible as a `__GIMPLE`-safe C
    # literal — `_signed_int64_c_literal`'s own INT64_MIN form
    # `(-0x7FFFFFFFFFFFFFFFLL - 1)` is a hard gimple-frontend error
    # ("expected expression before '(' token") inside `__GIMPLE` functions,
    # and `bounds()` is one (measured minlit_test.c, 2026-10-22). A non-list
    # iterator arg (e.g. `_CountIterator`, whose default bounds() could put
    # a None in slot 1) would need a true value-level Optional
    # representation — the staged next mechanism.
    template_src = template_src.replace(
        "if not a_bounds[1] or not initial_b_bounds[1]:",
        "if False:",
    )
    m = head_match(template_src)
    if not m:
        raise ValueError("monomorphize: no generic `fn`/`struct name[...]` found")
    kind, name = m.group(1), m.group(2)
    mangled = mangle(name, type_args)

    # Guard against substituting a type param that's also used as a binding name
    # (silent miscompile otherwise — review finding #3).
    _check_no_value_shadow(template_src, list(type_args.keys()))

    # Drop the [type-params] block and rename the definition (fn or struct).
    src = template_src[:m.start()] + f"{kind} {mangled}" + template_src[m.end():]
    # A type parameter that is ITSELF spelled like a receiver convention
    # (`_ListIter[mut: Bool, ...]` — `mut` is both the parameter name and the
    # receiver convention): the bare-word pass must not rewrite the `mut` of a
    # receiver marker (`def __next__(mut self)`), or the marker is destroyed
    # and the method compiles with an EXTRA parameter glued to the receiver —
    # the C signature takes 2 args where the caller's `next(<struct>)`
    # dispatch passes 1, a hard gcc "too few arguments" error. The receiver
    # position is exactly `<modifier> self` (the modifier may sit on its own
    # line, as stdlib spells it), and only that occurrence is excluded.
    # (The parameter's other mentions — its own declaration block, docstring,
    # annotation use — are still substituted; the docstring rewrite is
    # cosmetic and codegen-irrelevant.)
    # Substitute each type parameter with its concrete type (whole-word),
    # skipping any nested scope that shadows this specific name. The
    # `Self.<param>` pass runs FIRST and consumes those occurrences whole.
    # A LIST value is a VARIADIC binding (`*Ts` -> every remaining call
    # argument) and takes the dedicated pass instead: the body spells the
    # parameter without the star, so the plain passes would never reach it.
    for tp, concrete in type_args.items():
        if isinstance(concrete, (list, tuple)):
            src = _sub_variadic(src, tp, list(concrete), element_map,
                                self_element)
            continue
        spans = _shadowed_spans(src, tp)
        if tp in _RECEIVER_MODS:
            spans = spans + [
                (m.start(), m.end())
                for m in re.finditer(rf'\b{re.escape(tp)}\s+(?=\bself\b)', src)
            ]
        src = _sub_outside_spans(rf'\bSelf\.{re.escape(tp)}\b', str(concrete),
                                 src, spans)
        # `(?<!\.)`: a MEMBER NAME of a dotted access is not a reference to
        # this template's parameter. `struct BitSet[size: Int]` spells
        # `comptime if resized_from.size < Self.size:` in its cross-size
        # copy constructor (stdlib/std/collections/bitset.mojo:192/213):
        # `Self.size` is this instantiation's own size and the unit pass
        # above already consumed it, but `resized_from.size` is the SOURCE
        # instance's size — a member read whose name merely happens to be
        # spelled like the parameter. Rewriting it glued the concrete value
        # onto the dot (`resized_from.128`), and the lexer's FLOAT
        # alternative (`\.\d...`) then read `.128` as a single FLOAT token —
        # so the re-parse of the monomorphized .mojo file died on the first
        # such line with `Expected COLON got FLOAT('.128')` (measured 2026-
        # 10-26 on BitSet_4_size_3_128.mojo:86 — EVERY BitSet[N] hit it,
        # since the constructor is in every instantiation), while the
        # un-rewritten spelling parses cleanly. The lookbehind only sees a
        # dot that PRECEDES the parameter, so a dotted TYPE PREFIX
        # (`var _inner: T.Element` — the `_check_no_value_shadow` annotation
        # case, where `T` is the parameter and `.Element` follows it) is
        # still rewritten exactly as before.
        #
        # `(?![ \t]*=(?!=))`: a KEYWORD LABEL of a bracket/call argument is
        # not a reference to this template's parameter, either. The stdlib
        # SIMD struct spells its reduction entry points
        # `self.reduce[max[dtype=Self.dtype], size_out]()` (simd.mojo:3106;
        # `min[dtype=Self.dtype]` at 3146) — the `dtype` before the `=` is
        # the CALLEE's comptime-parameter name, a label, and the unit pass
        # above has just rewritten its VALUE (`Self.dtype` -> the concrete
        # arg) beside it. Rewriting the label too produced
        # `max[exp.dtype=exp.dtype]` (for the `__pow__` call site's
        # `SIMD[exp.dtype, self.length]` spelling) — and, identically,
        # `max[Float32=Float32]` for the fully concrete `SIMD[Float32, 8]`:
        # EVERY SIMD instantiation hit the same line, and the re-parse died
        # with `Expected RBRACKET got ASSIGN('=')` where the label's `=`
        # sat inside the outer `reduce[...]` argument list (measured
        # 2026-10-27 on SIMD_5_dtype_14_exp_....mojo:2662, the reduce_max
        # body: template line 3106 is generated line 3106-445+1). A label is
        # the parameter immediately followed by a single `=` (the `(?!=)`
        # tail keeps a `==` comparison — where the parameter IS a reference
        # — substitutable); `[ \t]*` rather than `\s*` so a parameter at
        # end of line whose NEXT line begins a `=` (an annotation with a
        # wrapped default) is still a reference and still rewritten.
        src = _sub_outside_spans(
            rf'(?<!\.)\b{re.escape(tp)}\b(?![ \t]*=(?!=))', str(concrete),
            src, spans)
    return mangled, src


# Receiver-convention spellings a type parameter may be named after (the
# parser's ownership vocabulary, fire_compiler's `_CONV_*` sets plus the
# transfer/move spellings). `monomorphize_source` must protect a
# `<param> self` receiver marker when the parameter is spelled like one of
# these, and `instantiate` folds that guard into the CAS key (a pre-guard
# cache entry for such a template carries the corrupted `True self` form).
_RECEIVER_MODS = frozenset(
    {'mut', 'inout', 'out', 'var', 'owned', 'read', 'ref', 'imm',
     'borrowed', 'borrow', 'delete'})


def compile_fn(fn_src: str, gcc: str = None) -> tuple:
    """Compile a concrete (non-generic) single-`fn` source to a CAS-cached object,
    keyed by its content. Used for overload instances (slice 4). Returns
    (object_path, hit)."""
    gcc = gcc or find_gcc()
    m = re.search(r'\b(?:fn|def)\s+(\w+)', fn_src)
    name = m.group(1) if m else 'fn'
    key = cas.instantiation_key(fn_src, {'__fn__': name}, None, gcc, _OBJ_FLAGS)

    def build():
        gen = GimpleGen(emit_entry_points=False, module_name=name)
        c = gen.gen_module(Parser(py_tokenize(fn_src)).parse_module())
        wd = tempfile.mkdtemp(prefix='mojo_ovl_')
        cf, of = os.path.join(wd, name + '.c'), os.path.join(wd, name + '.o')
        with open(cf, 'w') as f:
            f.write(c)
        subprocess.run([gcc, *_OBJ_FLAGS, '-c', '-o', of, cf], check=True)
        with open(of, 'rb') as f:
            return f.read()

    return cas.get_or_build(key, '.o', build)


_IN_PROGRESS: set = set()
# Current nesting depth of instantiation builds (for the optional MOJO_ELAB_LOG
# diagnostic). Deep-but-finite concrete cascades are fine; the thing that must
# never happen is instantiating with non-concrete (symbolic) type args, which is
# guarded at the call site (GimpleGen._elaborate_generic_call / _is_concrete_type_arg).
ELAB_DEPTH: list = [0]


def instantiate(template_src: str, type_args: dict, comptime_args: dict = None,
                gcc: str = None, nested_defs: list = None,
                renames: list = None) -> tuple:
    """Instantiate template_src for type_args, via the shared CAS.
    Returns (mangled_name, object_path_or_None, hit, cpp_object_path_or_None)
    — both object results are PATHS into the CAS (cas.get_or_build's own
    return convention: an artifact path, not its bytes), matching the
    existing `object_path_or_None` contract exactly.

    `nested_defs` / `renames` splice nested-struct definitions into the
    translation unit (see the note at the splice site below): each entry of
    `nested_defs` is a monomorphized, mangled-named struct definition to
    place AHEAD of the template, and each `(raw, mangled)` pair of `renames`
    is rewritten throughout the template (and the nested defs) so a by-value
    nested field resolves to the real layout. Both fold into the CAS key, so
    a nested instantiation never collides with the plain one of the same
    (template, type_args).

    `cpp_object_path` is non-None exactly when the instantiated template
    contains a nested `async def`/generator this codegen compiles to a real
    C++20 coroutine translation unit (GimpleGen.generated_cpp, populated by
    the SAME gen_module() call that produces the ordinary GIMPLE `.c` side —
    see gen_module's own preamble-assembly step) — test_locks.mojo's/test_
    tracing.mojo's own shape (`test_tracing[level, enabled]()` containing
    `async def test_tracing_add[...](...): ...`). Compiled with g++ (C++20)
    into its own object, CAS-cached under the SAME instantiation key as the
    `.c` side but a distinct `.cpp.o` extension (cas.get_or_build's `(key,
    ext)` pair already supports this — no new storage layer needed, just a
    second extension under the identical key). The caller must link this
    object in (in addition to the `.o`) via a C++-aware link driver
    (g++, or gcc + `-lstdc++`) — see gimple_codegen.py's `_link_needs_cxx`
    and driver.py's own handling of it.

    Before this, `build()` only ever asked for `gen`'s ordinary `.c` output
    — `gen.generated_cpp` was silently discarded entirely, so ANY generic
    whose body needed a coroutine translation unit either corrupted (via
    monomorphize_source's blind textual substitution touching a nested,
    shadowed bracket-parameter declaration — see monomorphize_source's own
    `_shadowed_spans` handling) or produced a `.c` that referenced an
    async-unit symbol nothing ever defined (an undefined-symbol link
    failure, or — before gimple_codegen.py's own upfront nested-async
    detection was added — a much worse SILENT placeholder-`0` miscompile;
    see bugs/CODEGEN_comptime_bracket_parametrized_function_calls_
    silently_wrong.md's test_tracing.mojo analysis)."""
    gcc = gcc or find_gcc()
    mangled, concrete = monomorphize_source(template_src, type_args)
    # A nested generic-struct TYPE ARGUMENT (a mention like `_ListIter[True,
    # Int, ...]` substituted for the template's parameter) does not resolve in
    # the isolated translation unit: a fresh GimpleGen has no registration for
    # it, so a BY-VALUE field `var _inner: _ListIter[...]` erases to int64_t —
    # one word where the layout is three — and every method the wrapper calls
    # on it (`next(self._inner)`) falls into the `next`-on-unresolvable-
    # receiver refusal. `nested_defs` splices the nested struct's own
    # monomorphized DEFINITION (fields + methods, already renamed to its
    # mangled name by monomorphize_source) ahead of the template, and
    # `renames` rewrites each nested mention in the template body to that
    # mangled name, so the by-value field gets the real layout and the method
    # calls resolve against the definition in the same TU. (The
    # explicit-bracket path's established behaviour — the mangled nested name
    # erases to int64_t/pointer inside the isolated body — stands for
    # pointer-only uses, which are ABI-harmless; this splice is what a by-
    # value use needs. See Elaborator.elaborate_generic_struct's `nested`.)
    # CAS-key guard for the receiver-marker fix in monomorphize_source: a
    # template whose parameter list is named after a receiver convention
    # (`_ListIter[mut: Bool, ...]`) monomorphizes to DIFFERENT text than it
    # did before that fix (the `<param> self` marker is preserved instead of
    # rewritten to the concrete value) — but the pre-fix output is keyed on
    # the SAME (template, type_args) content. Any such entry cached before
    # the fix (a `True self`-corrupted `__next__` with an extra parameter)
    # would be served to this build and link as the wrong signature. The
    # guard is a deterministic function of (template, type_args), so folding
    # it into the key material reroutes ONLY the affected instantiations to a
    # fresh entry; every other plain instantiation keeps its exact v1 key and
    # its cached object.
    _recv_guard = any(_tp in _RECEIVER_MODS for _tp in (type_args or {}))
    _nested_extra = None
    if nested_defs or renames or _recv_guard:
        # Longest mention first: a nested mention CONTAINS its deeper
        # mentions verbatim, so replacing the inner one first would break the
        # outer match (`A[B[C]]` — rename `B[C]` first and `A[B[C]]` no
        # longer matches as a whole).
        for _raw, _repl in sorted(renames or [], key=lambda r: -len(r[0])):
            concrete = concrete.replace(_raw, _repl)
        _defs = []
        for _d in (nested_defs or []):
            for _raw, _repl in sorted(renames or [], key=lambda r: -len(r[0])):
                _d = _d.replace(_raw, _repl)
            _defs.append(_d)
        concrete = '\n'.join(_defs) + '\n' + concrete
        _nested_extra = (tuple(renames or []), tuple(_defs), _recv_guard)
    key = cas.instantiation_key(template_src, type_args, comptime_args, gcc,
                                _OBJ_FLAGS, extra=_nested_extra)

    _log = os.environ.get('MOJO_ELAB_LOG')
    if _log:
        with open(_log, 'a') as _f:
            _re_entrant = ' RE-ENTRANT' if key in _IN_PROGRESS else ''
            _f.write(f"{ELAB_DEPTH[0]:3d} instantiate {mangled}  targs={type_args}{_re_entrant}\n")

    # Recursive generic (e.g. a self-referential instantiation, or a mutual cycle
    # A→B→A): the symbol is already being built by an outer frame. Return it without
    # rebuilding to break the cycle — the outer frame contributes the .o; this
    # reference just needs the (already-known) mangled symbol. Its signature is
    # recovered from the concrete source by the caller, not from the object.
    if key in _IN_PROGRESS:
        return mangled, None, True, None

    # Smuggled out of build() (cas.get_or_build's contract is a single
    # bytes-returning build_fn keyed by one (key, ext) pair — the cpp side,
    # when present, is published separately below via a second, explicit
    # cas.publish/lookup pair under the SAME key but a different ext,
    # rather than teaching cas.get_or_build a multi-artifact return shape
    # for this one caller).
    _cpp_bytes: dict = {}

    def build():
        # The instantiated function is already uniquely named (mangled); don't
        # overload-suffix it, or the caller's reference (info['symbol'] = mangled)
        # won't match the definition.
        wd = tempfile.mkdtemp(prefix='mojo_inst_')
        # Several of gen_module's own passes (notably the "Async closures/
        # functions NESTED INSIDE A TOP-LEVEL FUNCTION" pass — a nested
        # `async def` with its OWN comptime bracket params, test_tracing.
        # mojo's real `test_tracing_add[enabled, lhs](...)`/`test_tracing_
        # add_two_of_them[enabled](...)` shape) are gated on `self.
        # _current_filename` being a REAL, readable path (`if _gsrc:` after
        # `open(self._current_filename).read()`) — they re-read the source
        # textually (for a bracket-parameter type-annotation scan
        # `monomorphize_source` doesn't preserve in the AST). Previously
        # never set here at all, so EVERY such pass silently no-opped for
        # an elaborated fragment specifically (never for an ordinary
        # top-level module compile, which always sets this) — a nested
        # async-with-comptime-params inside a generic fell all the way
        # through to gen_module's own final "still unsupported" whole-
        # module refusal, honest but wrong (the mechanism to actually
        # compile it already existed, it just never saw this source at
        # all). Write the CONCRETE (already-monomorphized) source to a
        # real file and point `_current_filename` at it — the exact same
        # convention module_may_have_supported_generator/build_executable
        # use for the top-level module's own file.
        mfile = os.path.join(wd, mangled + '.mojo')
        with open(mfile, 'w') as f:
            f.write(concrete)
        # `module_name=''`, NOT `module_name=mangled`. This is load-bearing and
        # was a real defect (measured 2026-10-02): a struct method's C symbol
        # is composed as `{home-module}_{Struct}_{method}{overload_suffix}`
        # (`mojo/middle/funcs_shared.py::_struct_method_qualifier`), and
        # passing `mangled` as the module name made the instantiation TU emit
        #
        #     MoveOnly_Int64_MoveOnly_Int64___init__      <- what the TU defined
        #
        # while the CALLER — `_register_generic_struct`, which declares
        # `extern void MoveOnly_Int___init__ (MoveOnly_Int *, int64_t);` and
        # keys `func_return_types` on the same bare name, because a
        # materialized generic struct has no entry in `_imported_struct_home`
        # and therefore no qualifier — declared
        #
        #     MoveOnly_Int___init__                        <- what the caller wants
        #
        # Two names, one link. Verified by linking `test/collections/
        # test_array.mojo`'s generated C against its own CAS instantiation
        # object: `ld: undefined _MoveOnly_Int___init__`. So every generic
        # struct this elaborator had ever materialized produced an artifact
        # that could not link, and `compile_stdlib.py` (`gcc -fsyntax-only`)
        # cannot see it. The top-level function needs no qualifier either and
        # is protected by `no_mangle` below, so `''` changes nothing about it
        # (`empty_Int` measures identical before and after).
        gen = GimpleGen(emit_entry_points=False, module_name='', no_mangle={mangled})
        gen._current_filename = mfile
        c = gen.gen_module(Parser(py_tokenize(concrete)).with_filename(mfile).parse_module())
        cfile, ofile = os.path.join(wd, mangled + '.c'), os.path.join(wd, mangled + '.o')
        with open(cfile, 'w') as f:
            f.write(c)
        # The gcc stderr travels in the exception. `check=True` raises
        # CalledProcessError, which carries no output, so a build that failed
        # here reported only "Command ... returned non-zero exit status 1" —
        # and the caller that most needs it (`_ensure_generic_struct`, which
        # elaborates a struct into a constructor call) turned it into a
        # silently different program. See that function's own comment.
        #
        # …and it is RETRIED, because this one step is the only impure thing
        # in `elaborate_generic_struct` and it is impure in a way that has
        # produced a one-off: on an 18-worker sweep every worker spawns gcc for
        # every instantiation it needs, and a `gcc -c` that loses its output
        # file to the OS is not the same failure as a `gcc -c` that rejected
        # the source. A retry is defensible here precisely because the build is
        # CONTENT-KEYED and DETERMINISTIC (`cas.instantiation_key` covers the
        # template source, the type args, the gcc and the flags): a second
        # attempt either succeeds — which is the transient, caught — or fails
        # with the SAME stderr, which is a real defect and still raised. So the
        # retry cannot turn a red into a green; it can only catch a signal.
        #
        # Every failed attempt's stderr is kept and printed with the final
        # exception, so "it worked on the third try" is visible to whoever
        # reads the next occurrence rather than being silently smoothed over.
        _OBJ_ATTEMPTS = 3
        _cc = None
        _seen_err: list = []
        for _attempt in range(_OBJ_ATTEMPTS):
            _cc = subprocess.run([gcc, *_OBJ_FLAGS, '-c', '-o', ofile, cfile],
                                 capture_output=True, text=True)
            if _cc.returncode == 0:
                break
            _seen_err.append(f"attempt {_attempt + 1} of {_OBJ_ATTEMPTS}: "
                             + (_cc.stderr or _cc.stdout or '<no output>')[-1200:])
        if _cc.returncode != 0:
            raise RuntimeError(
                f"gcc -c failed for the monomorphized {mangled} "
                f"(exit {_cc.returncode}, {_OBJ_ATTEMPTS} attempts); generated C "
                f"is at {cfile}\n" + '\n---\n'.join(_seen_err))
        if gen.generated_cpp:
            gxx = find_gxx()
            cppfile = os.path.join(wd, mangled + '_async.cpp')
            cppofile = os.path.join(wd, mangled + '_async.o')
            with open(cppfile, 'w') as f:
                f.write(gen.generated_cpp)
            subprocess.run([gxx, *_CPP_FLAGS, '-c', '-o', cppofile, cppfile], check=True)
            with open(cppofile, 'rb') as f:
                _cpp_bytes['data'] = f.read()
        with open(ofile, 'rb') as f:
            return f.read()

    _IN_PROGRESS.add(key)
    ELAB_DEPTH[0] += 1
    try:
        obj, hit = cas.get_or_build(key, '.o', build)
        if not hit and 'data' in _cpp_bytes:
            # First build of this instantiation, and it genuinely needed a
            # coroutine unit: publish it now (build() already ran above).
            cas.publish(key, '.cpp.o', _cpp_bytes['data'])
        # A PATH (cas.lookup's own return convention), not bytes — matches
        # `obj` above exactly, so callers can treat both uniformly (e.g.
        # gimple_codegen.py's `_link_objects`, ultimately passed straight
        # to a linker command line / cas.file_digest(path), never read as
        # in-memory bytes anywhere on that path).
        cpp_obj = cas.lookup(key, '.cpp.o')
    finally:
        ELAB_DEPTH[0] -= 1
        _IN_PROGRESS.discard(key)
    return mangled, obj, hit, cpp_obj
