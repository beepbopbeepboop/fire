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
        if re.search(rf'\b(?:var|for)\s+{e}\b', src) or \
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


def monomorphize_source(template_src: str, type_args: dict) -> tuple:
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
    (see bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md).
    Substituting the qualified form first also keeps the bare pass from
    double-substituting it — by then no `Self.<param>` text survives."""
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
    # Substitute each type parameter with its concrete type (whole-word),
    # skipping any nested scope that shadows this specific name. The
    # `Self.<param>` pass runs FIRST and consumes those occurrences whole.
    for tp, concrete in type_args.items():
        spans = _shadowed_spans(src, tp)
        src = _sub_outside_spans(rf'\bSelf\.{re.escape(tp)}\b', str(concrete),
                                 src, spans)
        src = _sub_outside_spans(rf'\b{re.escape(tp)}\b', str(concrete), src, spans)
    return mangled, src


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
                gcc: str = None) -> tuple:
    """Instantiate template_src for type_args, via the shared CAS.
    Returns (mangled_name, object_path_or_None, hit, cpp_object_path_or_None)
    — both object results are PATHS into the CAS (cas.get_or_build's own
    return convention: an artifact path, not its bytes), matching the
    existing `object_path_or_None` contract exactly.

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
    key = cas.instantiation_key(template_src, type_args, comptime_args, gcc, _OBJ_FLAGS)

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
