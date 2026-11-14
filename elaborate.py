#!/usr/bin/env python3
"""elaborate.py — the CAS-backed semantic driver (ELABORATION.md).

Elaboration turns parametric Mojo into concrete Mojo by resolving and running the
compile-time parts. This is the demand-driven service the codegen calls into; it
*decides* what to instantiate and *records* the result, while the engines
(`monomorphize`, `comptime`) execute and the CAS caches.

Slice 1 — generic call elaboration: `Generic[TypeArgs](args)` from an imported
generic → instantiate the template for those type args (CAS-cached), and report
the concrete symbol + object + signature so the codegen can lower the call and
record the object on the link line.
"""
import textwrap
import re
import subprocess

import monomorphize as mm
from fire_compiler import (py_tokenize, Parser, FunctionDef, StructDef,
                          TraitDef, split_top_level_commas, VarDecl,
                          AssignStmt, IdentExpr, TupleExpr, StringLiteral,
                          BoolLiteral, IntLiteral, FloatLiteral,
                          ComptimeVarStmt, CallExpr, BinaryOp, UnaryOp,
                          SubscriptExpr,
                          align_value_error, _expr_constraint_text, MemberExpr)
from mojo.middle import comptime as _comptime
from mojo.middle.comptime import (eval_const, eval_const_bool_state, CONST_TRUE,
                                  CONST_FALSE, conforms_to)
from gimple_codegen import _mojo_type
from mojo.middle.types import _body_builds_struct_tuple


class ConformanceError(Exception):
    """A concrete type does not satisfy a generic's trait bound (slice 6).

    Raised when elaborating `f[T]`/`Struct[T]` whose type parameter carries a
    trait bound that the concrete type does not meet (it is missing a required
    method, or its signature differs). The message is the compile error a user
    sees."""


class WhereConformanceError(ConformanceError):
    """A `where` clause of a generic is provably false for the concrete type
    arguments (`where (N > 0, "N must be positive")`). A subclass of
    ConformanceError, so it is an ordinary conformance diagnostic to every
    caller, and it is the one the struct instantiation path re-raises: its
    trait-bound swallow exists for false positives of the bound check, and
    a where clause that folds to false is not one of those."""


# The generic head is `monomorphize.head_match`, which finds it with BRACKETS
# BALANCED rather than with a `[^\]]*` class -- a parameter whose type is itself
# a type application (`keys: List[T]`, `width: SIMD[dtype, width]`) puts a `]`
# inside the parameter list, and every reader below wants the whole list. This
# file used to carry its own two copies of that regex; one reader of one rule is
# the point: `head_match` counts brackets to its match, so a parameter whose
# type is a type application is one parameter and not two
# (`the variadic bracket arity and the `len(<display>)` fold (landed in e72a5f93)` §0a carries
# the before/after and `std/collections/type_dict.mojo` as the case).


#: One derived answer per distinct module source, bounded and FIFO. The answer is
#: a pure function of the text and of nothing else, which is what makes this
#: sound rather than a cache with an invalidation argument attached — the same
#: argument `formal/monomorph.py::_derived_from_source` makes for the same
#: reason. Keyed by the TEXT rather than by `id()`, because a key that is an
#: address can be handed to a different object once the first is freed
#: (`the `_walk_ast` re-scan bug (fixed; the memo and self-assign scan fixes are in the same commit).`'s hazard
#: 2), and hashing the text costs far less than the scan it stands in for.
#:
#: 8 entries, far above one elaboration's working set: the three readers below
#: ask about the SAME module within one call, and the module being re-asked
#: about is the one a re-instantiation touches. An eviction is a
#: re-derivation, never a wrong answer.
#:
#: THE ORDER IS A LIST BESIDE THE DICT rather than `next(iter(the_dict))`, which
#: is the spelling `formal/monomorph.py::_derived_from_source` uses and which
#: this file may not: `elaborate.py` is inside the self-host closure
#: (`cas.selfhost_inputs()` lists it, `formal/*` does not), and `next()` over a
#: container is one of the constructs the self-hosted codegen does not lower —
#: the same reason `_bind_comprehension_target` avoids it. `queue.pop()` in
#: `cas.py` is the shape that is proven to lower.
_BRACKET_DEPTH_CACHE = {}
_BRACKET_DEPTH_ORDER = []
_BRACKET_DEPTH_CACHE_MAX = 8


def _bracket_depth_by_line(module_src: str) -> tuple[int, ...]:
    """depths[j] = bracket nesting depth (from `([{`) in effect at the START
    of 0-indexed line `j` of `module_src.splitlines()`. Comment- and
    string-literal-aware (including triple-quoted docstrings and single
    backtick-delimited MLIR literals, e.g. `` `#interp.pointer<0> : ` `` —
    without backtick-awareness a literal `#` inside one of these is
    mistaken for a comment-start, silently swallowing the rest of the line
    including its closing bracket and permanently desyncing depth for the
    rest of the file) so a `[`/`]`/`(`/`)`/`{`/`}` inside a literal or
    comment is never mistaken for a structural bracket.

    Exists because a generic's header (`def name[T, /](args) -> Ret[...]:`)
    may itself span multiple physical lines, with a continuation line — e.g.
    the `]`/`)` that closes the parameter list — starting at column 0. A
    plain "dedent to <= base indentation ends the block" check misreads that
    continuation line as the end of the function/struct, silently truncating
    the extracted template before its real body.

    **A tuple, and memoised, and both are the same decision.** Three readers ask
    this question about the same module inside one elaboration
    (`extract_fn_source`, `extract_overloads`, `extract_struct_source`), each
    re-running the whole scan, and it was 5.4 s of tottime / 8.4 s cumulative of
    a 21.6 s instrumented `std/simd.mojo` build — 39% of what was left after
    `formal/monomorph.py`'s call-site fix, which is the measurement
    `bugs/PERF_formal_import_asks_are_products_of_the_closure.md` §4d records.

    It is a TUPLE rather than a list because the memo hands every reader the SAME
    object, and a reader that mutated it would corrupt every later one — the
    hazard the same doc's §"the memo's hazards" states for a shared list. A tuple
    removes it structurally rather than by a check that a future caller could
    forget: `_find_block_end` only READS it, so nothing has to be migrated.
    """
    cached = _BRACKET_DEPTH_CACHE.get(module_src)
    if cached is not None:
        return cached
    depth = 0
    depths = [0]
    in_str = None  # None, or '"', "'", '"""', "'''"
    i, n = 0, len(module_src)
    while i < n:
        c = module_src[i]
        if in_str:
            if in_str in ('"""', "'''"):
                if module_src.startswith(in_str, i):
                    i += 3
                    in_str = None
                    continue
            else:
                if c == '\\':
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
            if c == '\n':
                depths.append(depth)
            i += 1
            continue
        if c == '#':
            j = module_src.find('\n', i)
            i = n if j == -1 else j
            continue
        if module_src.startswith('"""', i) or module_src.startswith("'''", i):
            in_str = module_src[i:i + 3]
            i += 3
            continue
        if c in ('"', "'", '`'):
            in_str = c
            i += 1
            continue
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth = max(0, depth - 1)
        if c == '\n':
            depths.append(depth)
        i += 1
    out = tuple(depths)
    if len(_BRACKET_DEPTH_ORDER) >= _BRACKET_DEPTH_CACHE_MAX:
        _BRACKET_DEPTH_CACHE.pop(_BRACKET_DEPTH_ORDER.pop(0))
    _BRACKET_DEPTH_CACHE[module_src] = out
    _BRACKET_DEPTH_ORDER.append(module_src)
    return out


def _find_block_end(lines: list[str], depths: tuple[int, ...],
                    start: int, base: int) -> int:
    """First line index after `start` that both dedents to <= `base`
    indentation AND sits at bracket depth 0 — i.e. an ordinary top-level
    statement boundary, not a continuation of a still-open `([{` header."""
    for j in range(start + 1, len(lines)):
        l = lines[j]
        d = depths[j] if j < len(depths) else 0
        if l.strip() and d == 0 and (len(l) - len(l.lstrip())) <= base:
            return j
    return len(lines)


def _binds_from_args(template_src: str, arg_ctypes) -> bool:
    """True when every type parameter of the template is bound by unifying a
    parameter ANNOTATION with an argument's C type — i.e. WITHOUT leaning on
    `_fill_erased_params` or a declared default, which bind anything. That
    distinction is what tells `Scalar[dtype]` (bound by an int argument) from
    `Pointer[T, ...]` (T is erased-only, so it "binds" to whatever)."""
    params = type_param_names(template_src)
    if not params:
        return False
    fn = None
    for s in Parser(py_tokenize(template_src)).parse_module():
        if isinstance(s, FunctionDef):
            fn = s
            break
    if fn is None:
        return False
    bound = set()
    for i, (_pname, ann) in enumerate(fn.params):
        if i >= len(arg_ctypes):
            break
        bound.update(_unify_param_ann(ann, params, arg_ctypes[i]).keys())
    return all(p in bound for p in params)


def extract_fn_source(module_src: str, fn_name: str, arg_count: int | None = None,
                      arg_ctypes=None):
    """Pull the source text of a single `fn fn_name[...](...): body` from a
    module, by indentation (the generic template we'll instantiate). None if
    not found.

    A generic name can have multiple same-named definitions distinguished
    only by arity (e.g. `itertools.product` has separate `[IterableTypeA,
    IterableTypeB](a, b)` / `(a, b, c)` / `(a, b, c, d)` overloads — there is
    no separate "generic overload" mechanism the way non-generic overloads
    get one via `extract_overloads`). When `arg_count` is given and more than
    one candidate matches by name, pick the one whose non-self, non-variadic
    parameter count equals it; otherwise fall back to the first match."""
    lines = module_src.splitlines(keepends=True)
    pat = re.compile(rf'^(\s*)(?:fn|def)\s+{re.escape(fn_name)}\s*[\[\(]')
    depths = _bracket_depth_by_line(module_src)
    candidates = []
    i = 0
    while i < len(lines):
        if pat.match(lines[i]):
            base = len(lines[i]) - len(lines[i].lstrip())
            end = _find_block_end(lines, depths, i, base)
            candidates.append(''.join(lines[i:end]))
            i = end
        else:
            i += 1
    if not candidates:
        return None
    if arg_count is None or len(candidates) == 1:
        return candidates[0]
    first_arity_match = None
    for src in candidates:
        # A candidate may be a METHOD (the pattern allows leading whitespace),
        # whose text starts indented; parsing that as a module is an
        # `Unexpected INDENT` (a name defined both as a method and as a free
        # function, e.g. `is_amd_gpu` in std/sys/info.mojo). Dedent to parse;
        # the caller still gets the original text back.
        for s in Parser(py_tokenize(textwrap.dedent(src))).parse_module():
            if isinstance(s, FunctionDef) and s.name == fn_name:
                n = len([1 for pn, _ in s.params if pn != 'self' and not pn.startswith('*')])
                if n == arg_count:
                    if arg_ctypes is None:
                        return src
                    # Several generic overloads of the SAME arity differ only
                    # in their parameter types (`readfirstlane[T](value:
                    # Pointer[T, ...])` vs `readfirstlane[dtype](value:
                    # Scalar[dtype])`): the first by arity is not the one the
                    # call means. Take the first whose type parameters the
                    # call's argument types actually bind.
                    if first_arity_match is None:
                        first_arity_match = src
                    if _binds_from_args(src, arg_ctypes):
                        return src
                break
    if first_arity_match is not None:
        return first_arity_match
    return candidates[0]


def extract_overloads(module_src: str, fn_name: str):
    """All non-generic overloads of fn_name: list of (src, [param_mojo_types],
    ret_mojo_type), one per definition, by indentation."""
    lines = module_src.splitlines(keepends=True)
    pat = re.compile(rf'^(\s*)(?:fn|def)\s+{re.escape(fn_name)}\s*\(')
    depths = _bracket_depth_by_line(module_src)
    out = []
    i = 0
    while i < len(lines):
        if pat.match(lines[i]):
            base = len(lines[i]) - len(lines[i].lstrip())
            j = _find_block_end(lines, depths, i, base)
            src = ''.join(lines[i:j])
            fn = None
            for s in Parser(py_tokenize(src)).parse_module():
                if isinstance(s, FunctionDef):
                    fn = s
                    break
            if fn is not None:
                ptypes = [t for n, t in fn.params if n != 'self']
                out.append((src, ptypes, fn.return_type))
            i = j
        else:
            i += 1
    return out


def _is_param_marker(p: str) -> bool:
    """True for a `[...]` head entry that is a POSITIONAL-ONLY / KEYWORD-ONLY
    separator rather than a parameter name.

    Both spellings occur: the legacy `/` and `*`, and Mojo's current `//` and
    `**`. The list must be matched by CHARACTER, not by equality with `'/'`,
    because the current stdlib writes `//` — and an unrecognised `//` became a
    "type parameter" named `//` that `infer_type_args` was then required to
    bind from a call's arguments. Nothing can ever bind it, so EVERY template
    written with the current marker was declined outright: 903 of the 1254
    elaborator declines measured over the stdlib sweep, which is why
    `ceildiv`/`exp`/`sqrt`/`isnan`/`black_box` and the rest of the numeric
    library reached the generated C as bare externs (see
    bugs/imported-generic-elaboration-defect).
    """
    return bool(p) and all(ch in '/*' for ch in p)


def type_param_names(template_src: str):
    """The generic's type-parameter names — for `fn` or `struct`, e.g.
    `struct Box[T, U]` -> ['T', 'U']. Skips the positional-only / keyword-only
    separators (`/`, `//`, `*`, `**`), which are not parameter names — see
    `_is_param_marker` for why the marker test is by character."""
    m = mm.head_match(template_src)
    if not m:
        return []
    # `split_top_level_commas`, not `split(',')`: the parameter list may contain
    # a bracketed type argument of its own (`keys: SIMD[Tuple[Int, Int], 4]`),
    # and a plain split cuts that parameter in half and reports a type
    # parameter named `Int]` -- one reader of the parameter list, asked once.
    return [p.strip().split(':')[0].strip()
            for p in split_top_level_commas(m.params)
            if p.strip() and not _is_param_marker(p.strip())]


def type_param_defaults(template_src: str):
    """Map each bracket-parameter name that has a DEFAULT to that default's
    source text: `def size_of[type: AnyType, target: CompilationTarget =
    CompilationTarget.current()]()` -> {'target': 'CompilationTarget.current()'}.

    Mojo's bracket head is a Python-like parameter list, so a parameter there
    can be optional exactly as a value parameter can. That is not a rare
    flourish: `target: CompilationTarget = CompilationTarget.current()` is the
    second parameter of every target query in `std/sys/info.mojo`
    (`size_of`, `align_of`, `bit_width_of`, `simd_width_of`, `is_32bit`,
    `is_64bit`, …), and a defaulted value parameter (`copy: Bool = False`,
    `N: Int = 8192`) is the same shape. `elaborate_generic_call` used to
    require one explicit type arg per bracket parameter, so a call written
    exactly as the stdlib writes it — `size_of[UInt8]()` — was declined before
    anything was compiled, and its call site reached the generated C as a bare
    `extern int64_t size_of (...)`. See
    `bugs/imported-generic-elaboration-defect`.

    Only the text is returned; whether it is USABLE as a concrete argument is
    `_default_type_arg`'s question, and it is deliberately narrow."""
    m = mm.head_match(template_src)
    if not m:
        return {}
    out = {}
    for p in split_top_level_commas(m.params):
        p = p.strip()
        if not p or _is_param_marker(p) or '=' not in p:
            continue
        head, _, dflt = p.partition('=')
        out[head.split(':')[0].strip()] = dflt.strip()
    return out


#: Bracket-parameter annotations that name a compile-time VALUE rather than a
#: type.  The classification a bare literal bracket argument turns on: `[T]`
#: and `[T: AnyType]` are types, `[origin: Int]` and `[n: Bool]` are values.
#:
#: Deliberately an ALLOW-LIST of the scalar value types this path spells, not
#: "annotated and not `AnyType`": a trait-bounded type parameter (`[T: Movable]`,
#: `[T: Copyable]`) is annotated too, and reading one of those as a value would
#: let a bare literal bind a TYPE parameter and substitute `0` for `T` in the
#: body — the fabricated-answer outcome every refusal in this area exists to
#: prevent.  A value-typed parameter whose annotation is not in this set (an
#: `AddressSpace`, an `Origin[…]`) is left classified as a type, which refuses a
#: bare literal for it rather than guessing a substitution.
_VALUE_BRACKET_ANNOTATIONS = frozenset((
    "Int", "UInt", "Int8", "Int16", "Int32", "Int64",
    "UInt8", "UInt16", "UInt32", "UInt64",
    "Bool", "String", "StringLiteral", "IntLiteral", "FloatLiteral",
    "Float16", "Float32", "Float64",
))


def type_param_kinds(template_src: str):
    """`['type' | 'value', …]` per bracket parameter, in declaration order.

    The one question a bare literal bracket argument turns on, and the reason
    `type_param_names` (which strips the annotation and answers only names) is
    not enough for it: `Tagged[T, origin: Int]` is `['type', 'value']`, so a
    literal supplied for `origin` is a comptime VALUE argument, while
    `Pair[T]` is `['type']` and a literal supplied for `T` is a value in a
    type's position — `bugs/FORMAL_an_explicit_parameter_list_naming_a_comptime_
    value.md` is the wall this exists to tell apart.

    A parameter with NO annotation (`[T]`) is a type, and one annotated with a
    scalar value type (`origin: Int`, `n: Bool`) is a value.  See
    `_VALUE_BRACKET_ANNOTATIONS` for why the value half is an allow-list rather
    than the complement of `AnyType`.

    Same reader (`mm.head_match`, `split_top_level_commas`, `_is_param_marker`)
    as `type_param_names`/`type_param_defaults`, so the three cannot disagree
    about which entries are parameters or how many there are.
    """
    m = mm.head_match(template_src)
    if not m:
        return []
    out = []
    for p in split_top_level_commas(m.params):
        p = p.strip()
        if not p or _is_param_marker(p):
            continue
        head = p.split('=', 1)[0].strip()
        _name, sep, annot = head.partition(':')
        # The annotation's own head: `List[T]` -> `List`, `Origin[mut=x]` ->
        # `Origin`, `Movable where …` -> `Movable`.
        base = annot.strip().split('[', 1)[0].split('where', 1)[0].strip()
        out.append("value" if sep and base in _VALUE_BRACKET_ANNOTATIONS
                   else "type")
    return out


_DEFAULT_INT = re.compile(r'^-?\d+$')
_DEFAULT_TYPE_ROOT = re.compile(r'^([A-Z]\w*)\s*(?:\.|$)')


def _default_type_arg(default: str):
    """The concrete argument to substitute for a bracket parameter the caller
    did not supply, or None when its default does not name one we can prove.

    Two shapes are provable, and both are exact rather than inferred:

    * a literal — `copy: Bool = False`, `N: Int = 8192`, `offset: Int = 0`.
      The default IS the value; substituting it is the call the caller wrote.
    * a TYPE-named expression — `target: CompilationTarget =
      CompilationTarget.current()`. `CompilationTarget.current()` is a value
      OF that type (a singleton of it), so `CompilationTarget` is the type it
      denotes, and the stdlib's own `CompilationTarget` type name is the right
      concrete argument. The leading-uppercase requirement is the load-bearing
      part: Mojo spells types with a capital, and this codebase's whole
      type-resolution machinery already depends on that convention.

    Anything else binds NOTHING and the caller declines exactly as before —
    `element_type=_` (a wildcard), `origin_of()._mlir_origin` (a lowercase
    call), `words_en()` (a lowercase call). That discipline is the whole reason
    this is safe: a partially-understood default would substitute a name that
    means nothing and produce an instantiation that compiles and lies."""
    d = (default or '').strip()
    if not d:
        return None
    if _DEFAULT_INT.match(d) or d in ('True', 'False'):
        return d
    m = _DEFAULT_TYPE_ROOT.match(d)
    return m.group(1) if m else None


def bind_type_args(template_src: str, type_args):
    """{param: concrete} for a template's bracket parameters, filling any the
    caller did not supply from their DEFAULT (`type_param_defaults`). None when
    a parameter is missing and has no provable default, or when the template has
    no bracket parameters at all.

    Supplied arguments are taken POSITIONALLY — the same `zip` the caller
    already used — and only the trailing ones can come from a default, because
    only a trailing parameter can be omitted without changing the meaning of the
    ones before it.

    A TRAILING variadic parameter (`*Ts` — measured 2026-10-21, part 4:
    `_ChainedIterator[*Ts: Iterator]`, the `chain`/`zip` out-parameter
    factories' wrappers) consumes EVERY remaining supplied argument as a
    list — `len(supplied) > len(params)` is the variadic case, not an
    overflow to truncate (the pre-variadic truncation would have silently
    dropped all inners but the first)."""
    params = type_param_names(template_src)
    if not params:
        return None
    supplied = list(type_args or ())
    if not any(p.startswith('*') for p in params):
        if len(supplied) > len(params):
            supplied = supplied[:len(params)]
    defaults = type_param_defaults(template_src) if len(supplied) < len(params) else {}
    targs = {}
    for i, p in enumerate(params):
        if p.startswith('*'):
            # Variadic: all remaining supplied args bind to this ONE
            # parameter, as a list. It must be trailing (Mojo's variadic
            # position), and it needs at least one argument (an empty
            # `chain()` has no measured lifting shape — the seed's
            # container gate already requires >= 1 argument).
            if len(supplied) <= i:
                return None
            targs[p] = list(supplied[i:])
            break
        if i < len(supplied):
            targs[p] = supplied[i]
            continue
        dflt = _default_type_arg(defaults.get(p, ''))
        if dflt is None:
            return None
        targs[p] = dflt
    return targs


# ── Trait / conformance bound-checking (slice 6) ─────────────────────────
#
# A generic's type parameter may carry a *trait bound*: `fn f[T: Stringable]`
# or `struct Box[T: Stringable]`. The bound names a trait — an abstract set of
# required method signatures. Before instantiating the generic for a concrete
# type, elaboration verifies the type *conforms* (defines every required
# method, with matching parameter/return types). A non-conforming type yields
# a `ConformanceError` rather than a broken instantiation downstream.

# `[T: Trait, U: Other, count: Int]` — capture the bound that follows each
# type-param name. A param with no `: Bound` (or a value param like `count:
# Int`, which we treat as unbounded for our purposes) maps to None.
def parse_bounds(template_src: str):
    """Map each type-parameter name to its trait bound name (or None) from a
    generic's `[...]` head: `fn f[T: Stringable]` -> {'T': 'Stringable'}."""
    m = mm.head_match(template_src)
    if not m:
        return {}
    bounds = {}
    for p in split_top_level_commas(m.params):
        p = p.strip()
        if not p or _is_param_marker(p):
            continue
        if ':' in p:
            name, bound = p.split(':', 1)
            # A parameter may be BOTH bounded and defaulted
            # (`target: CompilationTarget = CompilationTarget.current()`);
            # without this the bound read as the whole
            # 'CompilationTarget = CompilationTarget.current()' and every
            # conformance check silently degraded to "unknown trait, accept".
            bound = bound.partition('=')[0]
            bounds[name.strip()] = bound.strip() or None
        else:
            bounds[p.partition('=')[0].strip()] = None
    return bounds


def _method_sig(fn: FunctionDef):
    """(name, [param_mojo_types excluding self], ret_mojo_type) of a method."""
    ptypes = [t for n, t in fn.params if n != 'self']
    return (fn.name, ptypes, fn.return_type)


def extract_trait(module_src: str, trait_name: str):
    """The required method signatures of `trait trait_name`, as a list of
    (name, [param_types], ret_type). None if the trait is not defined here."""
    for s in Parser(py_tokenize(module_src)).parse_module():
        if isinstance(s, TraitDef) and s.name == trait_name:
            return [_method_sig(m) for m in s.methods]
    return None


def _extract_trait_def(module_src: str, trait_name: str):
    base, _ = _split_base_type_args(trait_name)
    try:
        for s in Parser(py_tokenize(module_src)).parse_module():
            if isinstance(s, TraitDef) and s.name == base:
                return s
    except Exception:
        return None
    return None


def type_methods(module_src: str, type_name: str):
    """The method signatures a concrete `struct type_name` defines, as a list
    of (name, [param_types], ret_type). None if the type is not a struct here."""
    for s in Parser(py_tokenize(module_src)).parse_module():
        if isinstance(s, StructDef) and s.name == type_name:
            return [_method_sig(m) for m in s.methods]
    return None


def _split_base_type_args(name: str):
    """'S[A,B]' -> ('S', ['A','B']); 'S' -> ('S', [])."""
    if not isinstance(name, str):
        return str(name), []
    name = name.strip()
    if '[' not in name:
        return name, []
    base, rest = name.split('[', 1)
    if not rest.endswith(']'):
        return name, []
    inner = rest[:-1].strip()
    if not inner:
        return base, []
    # split top-level commas
    args, depth, cur = [], 0, []
    for c in inner:
        if c in '([{': depth += 1
        elif c in ')]}': depth -= 1
        if c == ',' and depth == 0:
            args.append(''.join(cur).strip()); cur = []
        else:
            cur.append(c)
    if cur:
        args.append(''.join(cur).strip())
    return base, [a for a in args if a]


def _find_struct_def(module_src: str, type_name: str):
    try:
        stmts = Parser(py_tokenize(module_src)).parse_module()
    except Exception:
        return None, {}
    base, targs_list = _split_base_type_args(type_name)
    for s in stmts:
        if isinstance(s, StructDef) and s.name == base:
            return s, {'base': base, 'targs_list': targs_list}
    return None, {}


def _struct_targ_bindings(module_src: str, sd: StructDef, targs_list: list):
    bindings = {}
    try:
        tmpl = extract_struct_source(module_src, sd.name) or ''
        params = type_param_names(tmpl) if tmpl else []
        for i, p in enumerate(params):
            if i < len(targs_list):
                bindings[p] = targs_list[i]
    except Exception:
        pass
    # comptime aliases / constants on the struct (e.g. `comptime x = 0`)
    try:
        aliases = getattr(sd, 'comptime_aliases', None) or {}
        for k, v in aliases.items():
            try:
                val = eval_const(v, bindings)
            except Exception:
                val = None
            if isinstance(val, (bool, int, float, str)):
                bindings[k] = val
                bindings[f'Self.{k}'] = val
        # also scan fields/body for `comptime x = ...` / `alias x = ...` parsed as AssignStmt-like in some forms
        for fld in (getattr(sd, 'fields', None) or []):
            if isinstance(fld, AssignStmt) and isinstance(getattr(fld, 'target', None), IdentExpr):
                name = fld.target.name
                try:
                    val = eval_const(fld.value, bindings)
                except Exception:
                    val = None
                if isinstance(val, (bool, int, float, str)):
                    bindings.setdefault(name, val)
                    bindings.setdefault(f'Self.{name}', val)
            if isinstance(fld, ComptimeVarStmt):
                name = getattr(fld, 'target', None)
                if isinstance(name, str):
                    try:
                        val = eval_const(getattr(fld, 'value', None), bindings)
                    except Exception:
                        val = None
                    if isinstance(val, (bool, int, float, str)):
                        bindings.setdefault(name, val)
                        bindings.setdefault(f'Self.{name}', val)
    except Exception:
        pass
    return bindings


def _substitute_constraint_text(text: str, bindings: dict) -> str:
    if not text or not bindings:
        return text or ''
    out = text
    # replace Self.X, bare params
    for k, v in bindings.items():
        out = re.sub(rf'\bSelf\.{re.escape(k)}\b', str(v), out)
        out = re.sub(rf'\b{k}\b', str(v), out)
    return out


def _constraint_implied_for_evidence(method_where: str, assumption: str, module_src: str, bindings: dict) -> bool:
    """Conservative implication: does `assumption` imply `method_where`?
    Unknown/unparseable => True (accept, do not report)."""
    mw = _substitute_constraint_text(method_where or '', bindings).strip()
    if not mw:
        return True
    asn = _substitute_constraint_text(assumption or '', bindings).strip()
    # If method clause textually contained in assumption with simple and/or forms, accept.
    try:
        # Build conforms_to predicate and bases for evaluation
        cpred = _where_conforms_to_pred(module_src, bindings)
        # If assumption is empty (unconditional conformance), only accept if method clause
        # is provably true with no extra conforms_to facts.
        if not asn:
            st = eval_const_bool_state(Parser(py_tokenize(mw))._parse_expr(0), _where_bindings(bindings), conforms_to_pred=cpred)
            return st == CONST_TRUE
        # Try parsing and checking implication via text-level conservative rules.
        # If assumption implies method clause syntactically/structurally, accept.
        trait_bases, cache = _where_conformance_bases(module_src), {}
        if _constraint_implies_text(asn, mw, trait_bases, cache):
            return True
        # Also try evaluating method clause assuming conformance facts implied by assumption atoms.
        # Parse assumption as conforms_to facts and evaluate.
        # Conservative: if undecidable, accept.
        st = eval_const_bool_state(Parser(py_tokenize(mw))._parse_expr(0), _where_bindings(bindings), conforms_to_pred=cpred)
        if st == CONST_TRUE:
            return True
        # If assumption is a conforms_to(...) equal to method clause, accept.
        if mw == asn:
            return True
        # Try splitting assumption into and-atoms and see if they imply method clause
        # by evaluating with a custom predicate that returns True for atoms in assumption.
        a_atoms = set()
        try:
            aexpr = Parser(py_tokenize(asn))._parse_expr(0)
            a_atoms = set(_constraint_atoms(aexpr))
        except Exception:
            a_atoms = set()
        def _pred2(tname, trname):
            # resolve through bindings
            t = bindings.get(tname, tname)
            r = bindings.get(trname, trname)
            if cpred and cpred(t, r) is True:
                return True
            # check if conforms_to(t,r) implied by assumption atoms
            try:
                want = f"conforms_to({t}, {r})"
                # normalize simple forms
                for at in a_atoms:
                    if not isinstance(at, CallExpr):
                        continue
                    if isinstance(at.func, IdentExpr) and at.func.name == 'conforms_to' and len(at.args or []) == 2:
                        a0 = _expr_constraint_text(at.args[0])
                        a1 = _expr_constraint_text(at.args[1])
                        a0s = _substitute_constraint_text(a0, bindings)
                        a1s = _substitute_constraint_text(a1, bindings)
                        if a0s == str(t) and a1s == str(r):
                            return True
                        # ancestor implication
                        try:
                            bases = _where_conformance_bases(module_src)
                            if conforms_to(str(t), a1s, bases) is True and conforms_to(a1s, str(r), bases) is True:
                                return True
                        except Exception:
                            pass
            except Exception:
                pass
            return None
        st2 = eval_const_bool_state(Parser(py_tokenize(mw))._parse_expr(0), _where_bindings(bindings), conforms_to_pred=_pred2)
        if st2 == CONST_TRUE:
            return True
        return False if st2 == CONST_FALSE else True
    except Exception:
        # Conservative: unknown => accept
        return True


def check_conformance(module_src: str, type_name: str, trait_name: str):
    """Does concrete `type_name` satisfy `trait_name`? Returns (ok, missing)."""
    trait_base, trait_args = _split_base_type_args(trait_name)
    trait_def = _extract_trait_def(module_src, trait_base)
    if trait_def is None:
        return True, []
    required = [_method_sig(m) for m in trait_def.methods]
    sd, info = _find_struct_def(module_src, type_name)
    if sd is None:
        return True, []
    bindings = _struct_targ_bindings(module_src, sd, info.get('targs_list') or [])
    # bind trait type params from trait_name args if available (best-effort)
    try:
        tparams = [p[0] for p in (getattr(trait_def, 'params', None) or []) if isinstance(p, (list, tuple)) and p]
        for i, tp in enumerate(tparams):
            if i < len(trait_args):
                bindings.setdefault(tp, trait_args[i])
    except Exception:
        pass

    # find conformance assumption for trait (base or instantiated form)
    trait_bases, cache = _where_conformance_bases(module_src), {}
    assumption = None
    bc_items = list(getattr(sd, 'base_constraints', None) or [(_as_str(b), '') for b in (getattr(sd,'bases',None) or [])])
    # normalize bc names with substitutions
    def _bc_match(bname_s):
        bb, _ = _split_base_type_args(bname_s)
        if bname_s == trait_name or bb == trait_base:
            # if trait_name is parameterized, prefer exact instantiated match when present
            if trait_name == bname_s:
                return 2
            if bb == trait_base and ('[' not in trait_name or '[' in bname_s):
                return 1
        return 0
    # direct
    best = -1
    for bname, wtext in bc_items:
        bname_s = _substitute_constraint_text(_as_str(bname), bindings)
        wtext_s = _substitute_constraint_text(_as_str(wtext) if wtext is not None else '', bindings)
        sc = _bc_match(bname_s)
        if sc > best:
            best = sc
            if sc > 0:
                assumption = wtext_s
    # ancestor paths if not directly found
    if best <= 0:
        found = []
        for bname, wtext in bc_items:
            bname_s = _substitute_constraint_text(_as_str(bname), bindings)
            wtext_s = _substitute_constraint_text(_as_str(wtext) if wtext is not None else '', bindings)
            for anc, aw, path in _ancestors_with_paths(bname_s, wtext_s, trait_bases, cache):
                ab, _ = _split_base_type_args(anc)
                if anc == trait_name or ab == trait_base:
                    found.append(aw)
        if found:
            assumption = '' if any(a == '' for a in found) else found[0]
        else:
            assumption = None

    by_name = {}
    for m in (getattr(sd, 'methods', None) or []):
        sig = _method_sig(m)
        by_name.setdefault(sig[0], []).append((sig[1], sig[2], m))
    missing = []
    for tname, ptypes, ret in required:
        cands = by_name.get(tname)
        if cands is None:
            missing.append(f"missing method '{tname}'")
            continue
        impl = None
        for cp, cr, m in cands:
            if cp == ptypes and cr == ret:
                impl = m
                break
        if impl is None:
            want = f"({', '.join(ptypes)}) -> {ret}"
            missing.append(f"method '{tname}' signature mismatch (want {want})")
            continue
        mw = getattr(impl, 'where_clause', None)
        if mw is not None:
            mw_text = _expr_constraint_text(mw) if not isinstance(mw, str) else mw
            asn = assumption if assumption is not None else ''
            if not _constraint_implied_for_evidence(mw_text, asn, module_src, bindings):
                return False, [f"does not implement all requirements for '{trait_base}'"]
    return (not missing), missing


_FLOAT_DTYPES = {
    'Float64', 'Float32', 'Float16', 'BFloat16', 'Float8_E5M2', 'Float8_E4M3FN',
    'Float8_E5M2FNUZ', 'Float8_E4M3FNUZ', 'Float8_E4M3B11FNUZ'
}


def _is_float_dtype(t: str) -> bool:
    t = str(t).strip()
    if t in _FLOAT_DTYPES:
        return True
    # DType.float32 style
    if t.startswith('DType.'):
        name = t.split('.')[-1]
        if name in {'float64', 'float32', 'float16', 'bfloat16'}:
            return True
        if 'float' in name.lower():
            return True
    if 'float' in t.lower() and 'int' not in t.lower():
        # be conservative but check common cases
        if t in {'Float64', 'Float32'}:
            return True
    return False


def _is_int_dtype(t: str) -> bool:
    t = str(t).strip()
    if t.startswith('Int') or t.startswith('UInt'):
        # exclude floats
        if t.startswith('Float'):
            return False
        return True
    if t.startswith('DType.'):
        name = t.split('.')[-1]
        if name.startswith('int') or name.startswith('uint'):
            return True
    return False


def _template_where_clauses(template_src: str):
    """The parsed `where` clause expressions of a generic template (a function
    or a struct), as a list in source order, or None when the template does not
    parse. `(cond, "message")` entries are TupleExpr, as the parser leaves them."""
    try:
        stmts = Parser(py_tokenize(textwrap.dedent(template_src))).parse_module()
    except Exception:
        return None
    for s in stmts:
        if isinstance(s, (FunctionDef, StructDef)):
            w = s.where_clause
            if w is None:
                return []
            return list(w) if isinstance(w, list) else [w]
    return None


def _header_where_texts(template_src: str):
    """The source text of each `where` clause of a template's declaration
    header, in source order.

    Read from the header itself rather than from a regex over the whole
    template: a `where` inside the base list (`struct S[T](Movable where
    False)`) is part of the base list, not a clause of the declaration, and the
    parser already leaves it out of the clauses. The header runs to the first
    colon outside brackets and string literals; a clause runs to the next
    `where` at the same depth, or to an `else "<message>"` tail."""
    src = template_src
    depth, quote, end = 0, None, len(src)
    marks = []
    i = 0
    while i < len(src):
        c = src[i]
        if quote:
            if c == '\\':
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in '"\'':
            quote = c
        elif c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        elif c == ':' and depth == 0:
            end = i
            break
        elif (depth == 0 and src.startswith('where', i)
                and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] == '_'))
                and not (src[i + 5:i + 6].isalnum() or src[i + 5:i + 6] == '_')):
            marks.append(i)
        i += 1
    texts = []
    for k, start in enumerate(marks):
        stop = marks[k + 1] if k + 1 < len(marks) else end
        clause = src[start + len('where'):stop]
        clause = re.sub(r'\s+else\s+(["\']).*$', '', clause, flags=re.S)
        texts.append(clause.strip())
    return texts


def where_violation_error(kind: str, name: str, exc: 'WhereConformanceError'):
    """The user-facing error for a generic instantiation that violates a `where`
    clause. Every instantiation entry point (an explicit `Struct[...]` in a
    body, the in-TU elaboration queue) reports through this one function, so the
    modular wording (`error: invalid <kind> of '<name>': violated constraint`)
    does not depend on which path reached the check."""
    return RuntimeError(
        f"error: invalid {kind} of '{name}': violated constraint\n"
        f"note: {type(exc).__name__}: {exc}")


# ── Declaration-time conditional conformance checks ──────────────────
#
# (synthesis checks added in part 4: copy/move constructor synthesis under
# conditional conformance. They run as a separate declaration-time pass.)

def _trait_ancestor_closure(trait_name, trait_bases, cache):
    """All ancestors of `trait_name` reachable through known trait bases."""
    if trait_name in cache:
        return cache[trait_name]
    out = set()
    stack = list(trait_bases.get(trait_name, []))
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        for nxt in (trait_bases.get(cur) or []):
            if nxt not in out:
                stack.append(nxt)
    cache[trait_name] = out
    return out


def _parse_constraint_expr(text):
    if not text:
        return None
    try:
        toks = py_tokenize(text)
        expr = Parser(toks)._parse_expr(0)
        return expr
    except Exception:
        return None


def _constraint_atoms(expr):
    """Return (kind, expr_or_parts) for implication reasoning, or None if unknown."""
    if expr is None:
        return None
    if isinstance(expr, CallExpr) and isinstance(expr.func, IdentExpr) and expr.func.name == 'conforms_to':
        if len(expr.args) == 2 and isinstance(expr.args[0], IdentExpr) and isinstance(expr.args[1], IdentExpr):
            return ('conforms', expr.args[0].name, expr.args[1].name)
        return None
    if isinstance(expr, UnaryOp) and str(expr.op) == 'not':
        inner = _constraint_atoms(expr.operand)
        if inner is None:
            return None
        return ('not', inner)
    if isinstance(expr, BinaryOp) and str(expr.op) in ('and', 'or'):
        left = _constraint_atoms(expr.left)
        right = _constraint_atoms(expr.right)
        if left is None or right is None:
            return None
        return (str(expr.op), left, right)
    if isinstance(expr, TupleExpr):
        elems = getattr(expr, 'elements', []) or []
        if len(elems) == 1:
            return _constraint_atoms(elems[0])
    if isinstance(expr, IdentExpr):
        # Treat bare name as unknown/opaque for implication purposes.
        return None
    return None


def _conforms_implies(a, b, trait_bases, cache):
    # a, b are ('conforms', T, TraitName)
    if a[1] != b[1]:
        return False
    ta, tb = a[2], b[2]
    if ta == tb:
        return True
    return tb in _trait_ancestor_closure(ta, trait_bases, cache)


def _atom_implies(a, b, trait_bases, cache):
    if a is None or b is None:
        return False
    ak, bk = a[0], b[0]
    if ak == 'and':
        # conjunction implies a conjunct if either side does
        return _atom_implies(a[1], b, trait_bases, cache) or _atom_implies(a[2], b, trait_bases, cache)
    if ak == 'or':
        # or implies b only when every disjunct does
        return _atom_implies(a[1], b, trait_bases, cache) and _atom_implies(a[2], b, trait_bases, cache)
    if bk == 'and':
        # a implies (x and y) if it implies both
        return _atom_implies(a, b[1], trait_bases, cache) and _atom_implies(a, b[2], trait_bases, cache)
    if bk == 'or':
        # a implies (x or y) if it implies either
        return _atom_implies(a, b[1], trait_bases, cache) or _atom_implies(a, b[2], trait_bases, cache)
    if ak == 'conforms' and bk == 'conforms':
        return _conforms_implies(a, b, trait_bases, cache)
    if ak == bk == 'not':
        # conservative: not X implies not Y only if Y implies X? safer to require equality of atoms
        return _atom_implies(b[1], a[1], trait_bases, cache)
    # unknown / mixed: be conservative
    return a == b


def _constraint_implies_text(derived_text, base_text, trait_bases, cache):
    if not derived_text or not base_text:
        return False
    if derived_text.strip() == base_text.strip():
        return True
    da = _constraint_atoms(_parse_constraint_expr(derived_text))
    ba = _constraint_atoms(_parse_constraint_expr(base_text))
    if da is None or ba is None:
        # anything the checker cannot parse is ACCEPTED (no diagnostic)
        return True
    return _atom_implies(da, ba, trait_bases, cache)


def _ancestors_with_paths(base_name, base_where, trait_bases, cache, path=None):
    """Yield (ancestor, where_text, path_names) for all reachable ancestors including base."""
    if path is None:
        path = [base_name]
    yield (base_name, base_where, list(path))
    for parent in (trait_bases.get(base_name) or []):
        # Parent traits are unconditional in this part's model.
        yield from _ancestors_with_paths(parent, base_where, trait_bases, cache, path + [parent])


def _as_str(x):
    return '' if x is None else str(x)


def _struct_is_conditionally_register_passable(sd):
    base_constraints = list(getattr(sd, 'base_constraints', []) or [])
    if not base_constraints:
        base_constraints = [(_as_str(b), '') for b in (getattr(sd, 'bases', []) or [])]
    for bname, wtext in base_constraints:
        if _as_str(bname) == 'RegisterPassable' and _as_str(wtext):
            return True
    return False


def _base_type_name(ann):
    if ann is None:
        return ''
    s = _as_str(ann).strip()
    # strip common prefixes? not needed for simple cases
    if '[' in s:
        s = s.split('[', 1)[0]
    return s.strip()


# ── Comptime member requirements (trait conformance part 5) ──────────
#
# A trait may require a `comptime` member:
#
#     trait EnumLike:
#         comptime _enum_is_exhaustive: Bool
#
# and a conforming struct supplies it as a struct-level comptime alias. This
# check runs at declaration time, beside the conditional-conformance pass,
# because only there is the trait's body visible next to every conformance;
# `check_conformance` sees one instantiation at a use site.
#
# Two conservatisms keep it from rejecting legal stdlib code:
#
#   * A missing member is NOT an error. These members are routinely
#     compiler-synthesised (`__copy_ctor_is_trivial` for `Copyable`,
#     `_enum_case_names` for `EnumLike`) and never appear in this tree's AST
#     for a struct that relies on the synthesis. Only a member the struct
#     actually declares can be judged.
#   * A value whose type the checker cannot name is accepted. `comptime
#     Element = Self.T` under `comptime Element: Movable` is the common
#     stdlib spelling and proves nothing either way here; only a known scalar
#     (or value-literal) type that is a different scalar than the required
#     one is rejected — exactly the `comptime _enum_is_exhaustive = 5` case.
#     Unknown relations stay accepted, the rule part 2's evidence check uses.

# A value-literal type and the scalar it materialises as. `IntLiteral[5]`
# reaches `_base_type_name` as `IntLiteral`, which is why the comparison is on
# the base name.
_COMPTIME_MATERIALIZED = {
    'Bool': ('Bool', 'BoolLiteral'),
    'Int': ('Int', 'IntLiteral'),
    'UInt': ('UInt', 'UIntLiteral'),
    'String': ('String', 'StringLiteral'),
    'Float64': ('Float64', 'FloatLiteral'),
}
_COMPTIME_KNOWN_SCALARS = {
    'Bool', 'BoolLiteral', 'Int', 'IntLiteral', 'UInt', 'UIntLiteral',
    'String', 'StringLiteral', 'Float64', 'FloatLiteral',
}


def _comptime_member_value_type(val):
    """The scalar type a comptime member's literal value has, or ''.

    Only a literal has a type this pass can name. An identifier, member
    access or call (`Self.T`, `Int`, `Tuple[Int, T]`, `IsTriviallyMovable[T]`)
    denotes a type or comptime value the checker cannot resolve, so it returns
    '' and the caller accepts the declaration.
    """
    if isinstance(val, BoolLiteral):
        return 'Bool'
    if isinstance(val, IntLiteral):
        return f'IntLiteral[{getattr(val, "value", 0)}]'
    if isinstance(val, StringLiteral):
        return 'StringLiteral'
    if isinstance(val, FloatLiteral):
        return 'FloatLiteral'
    return ''


def _comptime_member_effective_type(sd, name):
    """(type_str, where_str, found) for the struct comptime member `name`."""
    aliases = getattr(sd, 'comptime_aliases', None) or {}
    if name not in aliases:
        return '', '', False
    member_types = getattr(sd, 'comptime_member_types', None) or {}
    type_ann = _as_str(member_types.get(name, '')).strip()
    if type_ann:
        actual = type_ann
    else:
        actual = _comptime_member_value_type(aliases.get(name))
    wheres = getattr(sd, 'comptime_member_wheres', None) or {}
    return actual, _as_str(wheres.get(name, '')).strip(), True


def _comptime_type_conforms(actual: str, required: str) -> bool:
    """Conservative: reject only a KNOWN non-conformance.

    A known scalar actual conforms to its own (materialised) scalar and to
    `AnyType`; against a required scalar it is a different scalar, so reject.
    A required trait/user type and an opaque actual are both outside the
    model, so accept.
    """
    a = _base_type_name(actual)
    r = _base_type_name(required)
    if not a or not r:
        return True
    if a == r or r == 'AnyType':
        return True
    accepted = _COMPTIME_MATERIALIZED.get(r)
    if accepted is None:
        return True
    if a in accepted:
        return True
    if a in _COMPTIME_KNOWN_SCALARS:
        return False
    return True


def _struct_where_text(sd):
    """The struct header's `where` clauses as one `and`-joined condition."""
    w = getattr(sd, 'where_clause', None)
    if w is None:
        return ''
    parts = []
    for clause in (w if isinstance(w, list) else [w]):
        if isinstance(clause, str):
            cond = clause
        else:
            cond, _msg = _split_where_message(clause)
        try:
            text = cond if isinstance(cond, str) else _expr_constraint_text(cond)
        except Exception:
            continue
        if text.strip():
            parts.append(text.strip())
    return ' and '.join(parts)


def _constraint_expr_children(node):
    """The sub-expressions of a `where` clause node this walker descends."""
    if isinstance(node, CallExpr):
        children = [node.func] + list(node.args or [])
        for kwarg in (node.kwargs or []):
            children.append(kwarg[1])
        return children
    if isinstance(node, BinaryOp):
        return [node.left, node.right]
    if isinstance(node, UnaryOp):
        return [node.operand]
    if isinstance(node, TupleExpr):
        return list(getattr(node, 'elements', None) or [])
    if isinstance(node, SubscriptExpr):
        return [node.obj, node.index]
    if isinstance(node, MemberExpr):
        return [node.obj]
    return []


def _constraint_has_opaque_call(expr):
    """True when the clause calls something the implication rules don't model.

    `conforms_to` is the one call `_constraint_implied_for_evidence` reasons
    about. Anything else (`some_predicate(Self.n)`, `Ts.all[...]()`) is
    undecidable by design, and evaluating it yields FALSE rather than unknown,
    so the caller must not turn that into a diagnostic.
    """
    if isinstance(expr, CallExpr):
        if not (isinstance(expr.func, IdentExpr)
                and expr.func.name == 'conforms_to'):
            return True
    for child in _constraint_expr_children(expr):
        if child is not None and _constraint_has_opaque_call(child):
            return True
    return False


def _comptime_member_errors(struct_defs, trait_defs):
    """Declaration-time comptime member requirement diagnostics (part 5)."""
    trait_by_name = {}
    for td in (trait_defs or []):
        if isinstance(td, TraitDef):
            trait_by_name[_as_str(getattr(td, 'name', ''))] = td
    if not trait_by_name:
        return []
    errors = []
    for sd in (struct_defs or []):
        if not isinstance(sd, StructDef):
            continue
        sline = getattr(sd, 'line', 0) or 0
        base_constraints = list(getattr(sd, 'base_constraints', []) or [])
        if not base_constraints:
            base_constraints = [(_as_str(b), '')
                                for b in (getattr(sd, 'bases', []) or [])]
        struct_where = _struct_where_text(sd)
        for bname, wtext in base_constraints:
            bbase, _ = _split_base_type_args(_as_str(bname))
            td = trait_by_name.get(bbase)
            if td is None:
                continue
            reqs = list(getattr(td, 'comptime_members', None) or [])
            if not reqs:
                continue
            # The member's clause only has to hold under the conformance
            # constraint: a struct listing `Trait where n >= 10`, or itself
            # constrained by `n >= 10`, proves a `Self.n >= 10` member clause.
            assumption = _as_str(wtext) if wtext is not None else ''
            if struct_where:
                assumption = (f"({assumption}) and ({struct_where})"
                              if assumption else struct_where)
            for req in reqs:
                try:
                    rname, rtype, _rwhere = req
                except Exception:
                    continue
                rname = _as_str(rname)
                rtype = _as_str(rtype).strip()
                atype, awhere, found = _comptime_member_effective_type(
                    sd, rname)
                if not found:
                    # Compiler-synthesised conformance member; nothing the
                    # struct declared can be judged wrong.
                    continue
                bad = not _comptime_type_conforms(atype, rtype)
                if not bad and awhere:
                    try:
                        bindings = _struct_targ_bindings('', sd, [])
                    except Exception:
                        bindings = {}
                    # A member clause is written against `Self`, the struct
                    # header clauses against the bare parameter name.
                    for k in list(getattr(sd, 'bracket_params', []) or []):
                        bindings.setdefault(f'Self.{k}', k)
                    for k in list(getattr(sd, 'type_param_names', []) or []):
                        bindings.setdefault(f'Self.{k}', k)
                    if not _constraint_has_opaque_call(
                            _parse_constraint_expr(awhere)):
                        bad = not _constraint_implied_for_evidence(
                            awhere, assumption, '', bindings)
                if bad:
                    msg = (f"'{_as_str(sd.name)}' does not implement all "
                           f"requirements for '{bbase}'\n"
                           f"note: comptime member '{rname}' type "
                           f"'{atype or '?'}' does not conform to trait's "
                           f"required type '{rtype or '?'}'")
                    tline = getattr(td, 'line', 0) or 0
                    if tline:
                        msg += f"\nnote: trait '{bbase}' declared here"
                    errors.append((sline, msg))
                    break
    return errors



def _iter_function_defs(stmts):
    for s in (stmts or []):
        if isinstance(s, FunctionDef):
            yield s
        elif isinstance(s, StructDef):
            for m in (getattr(s, 'methods', None) or []):
                if isinstance(m, FunctionDef):
                    yield m
        elif isinstance(s, TraitDef):
            for m in (getattr(s, 'methods', None) or []):
                if isinstance(m, FunctionDef):
                    yield m


def check_conditional_rp_origin(stmts, struct_defs):
    """Reject returning ref[x] tied to a conditionally-RegisterPassable arg."""
    cond_rp = {}
    for sd in (struct_defs or []):
        if isinstance(sd, StructDef) and _struct_is_conditionally_register_passable(sd):
            cond_rp[_as_str(getattr(sd, 'name', ''))] = sd
    if not cond_rp:
        return
    for fn in _iter_function_defs(stmts):
        origin = _as_str(getattr(fn, 'return_origin', '') or '')
        if not origin:
            continue
        # find parameter named origin
        param_type = None
        is_ref_param = False
        for pname, ptype in (getattr(fn, 'params', None) or []):
            if _as_str(pname) == origin:
                param_type = ptype
                conv = (getattr(fn, 'param_convs', None) or {}).get(pname)
                # a ref argument is exempt
                if _as_str(conv) == 'ref':
                    is_ref_param = True
                break
        if is_ref_param or param_type is None:
            continue
        base = _base_type_name(param_type)
        if base in cond_rp:
            raise RuntimeError(
                f"cannot return '{origin}'s origin, because it might expand to a "
                f"RegisterPassable type")


def check_conformance_declarations(struct_defs, trait_defs):
    """Declaration-time checks for conditional trait conformance (part 1)."""
    trait_bases = {}
    for td in (trait_defs or []):
        if isinstance(td, TraitDef):
            trait_bases[_as_str(getattr(td, 'name', ''))] = list(getattr(td, 'bases', []) or [])
    cache = {}
    errors = []
    for sd in (struct_defs or []):
        if not isinstance(sd, StructDef):
            continue
        sline = getattr(sd, 'line', 0) or 0
        base_constraints = list(getattr(sd, 'base_constraints', []) or [])
        if not base_constraints:
            # fall back to unconditional bases if field missing/empty
            base_constraints = [(_as_str(b), '') for b in (getattr(sd, 'bases', []) or [])]

        bc_map = {}
        for bname, wtext in base_constraints:
            bc_map[_as_str(bname)] = _as_str(wtext) if wtext is not None else ''

        # Conditional TrivialRegisterPassable not supported
        for bname, wtext in base_constraints:
            if _as_str(bname) == 'TrivialRegisterPassable' and _as_str(wtext):
                errors.append((sline,
                    "conditional conformance to 'TrivialRegisterPassable' is not supported"))
                break

        # Collect ancestor reachability by ancestor name
        by_ancestor = {}
        for bname, wtext in base_constraints:
            bname = _as_str(bname)
            wtext = _as_str(wtext) if wtext is not None else ''
            for anc, awhere, path in _ancestors_with_paths(bname, wtext, trait_bases, cache):
                by_ancestor.setdefault(anc, []).append((awhere, path, bname))

        # Diamond: ancestor reached through different conditional paths must be explicit
        for anc, entries in by_ancestor.items():
            where_groups = {}
            for aw, path, direct in entries:
                where_groups.setdefault(aw, []).append((path, direct))
            if len(where_groups) <= 1:
                continue
            if anc in bc_map:
                continue
            errors.append((sline,
                f"ancestor trait '{anc}' is reached via multiple inheritance paths "
                f"with different constraints; it must be explicitly listed in the "
                f"conformance list with the desired constraint"))
            break

        # DerivedDoesNotImplyAncestor / UnconditionalDerivedConditionalAncestor
        for bname, wtext in base_constraints:
            bname = _as_str(bname)
            wtext = _as_str(wtext) if wtext is not None else ''
            broke = False
            for anc in _trait_ancestor_closure(bname, trait_bases, cache):
                if anc not in bc_map:
                    continue
                anc_where = bc_map[anc]
                if not wtext and anc_where:
                    errors.append((sline,
                        f"constraint for '{bname}' does not imply constraint for "
                        f"ancestor trait '{anc}'; strengthen the derived constraint "
                        f"by adding the ancestor's constraint with 'and'"))
                    broke = True
                    break
                if wtext and anc_where and not _constraint_implies_text(wtext, anc_where, trait_bases, cache):
                    errors.append((sline,
                        f"constraint for '{bname}' does not imply constraint for "
                        f"ancestor trait '{anc}'; strengthen the derived constraint "
                        f"by adding the ancestor's constraint with 'and'"))
                    broke = True
                    break
            if broke:
                break

    # Comptime member requirements (part 5)
    errors.extend(_comptime_member_errors(struct_defs, trait_defs))

    if errors:
        line, msg = sorted(errors, key=lambda x: x[0])[0]
        raise RuntimeError(f"error: {msg}")


# ── Copy/move synthesis under conditional conformance (part 4) ──────────

def _sd_base_constraints_map(sd):
    bc = list(getattr(sd, 'base_constraints', []) or [])
    if not bc:
        bc = [(_as_str(b), '') for b in (getattr(sd, 'bases', []) or [])]
    out = {}
    for bname, wtext in bc:
        out[_as_str(bname)] = _as_str(wtext) if wtext is not None else ''
    return out


def _sd_bracket_param_names(sd):
    names = []
    # Prefer explicit type parameter name lists when present.
    for attr in ('type_param_names', 'bracket_params'):
        vals = getattr(sd, attr, None) or []
        if isinstance(vals, list):
            for v in vals:
                if isinstance(v, (tuple, list)) and v:
                    n = _as_str(v[0]).lstrip('*')
                else:
                    n = _as_str(v).lstrip('*')
                if n and n not in names:
                    names.append(n)
    for bt in (getattr(sd, 'bracket_types', []) or []):
        if isinstance(bt, (tuple, list)) and bt:
            n = _as_str(bt[0]).lstrip('*')
            if n and n not in names:
                names.append(n)
    return names


def _ann_to_str(ann):
    if ann is None:
        return ''
    if isinstance(ann, str):
        return ann.strip()
    if isinstance(ann, IdentExpr):
        return _as_str(getattr(ann, 'name', '')).strip()
    # Best-effort: some AST nodes stringify reasonably.
    return _as_str(ann).strip()


def _split_top_level_type_args(text):
    s = (text or '').strip()
    if not s.startswith('[') or not s.endswith(']'):
        return None
    inner = s[1:-1]
    parts = []
    depth = 0
    cur = []
    for ch in inner:
        if ch in '([{<':
            depth += 1
            cur.append(ch)
        elif ch in ')]}>':
            depth -= 1
            cur.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur or inner.strip() == '':
        tail = ''.join(cur).strip()
        if tail or parts:
            parts.append(tail)
    return parts


def _parse_type_app(text):
    s = _ann_to_str(text)
    if not s:
        return '', []
    i = s.find('[')
    if i < 0 or not s.endswith(']'):
        return s, []
    base = s[:i].strip()
    args = _split_top_level_type_args(s[i:])
    if args is None:
        return s, []
    return base, args


def _subst_constraint_text(text, subs):
    if not text:
        return text
    # Replace longer keys first to avoid prefix collisions.
    for k in sorted(subs.keys(), key=len, reverse=True):
        v = subs[k]
        text = re.sub(rf'\b{re.escape(k)}\b', v, text)
    return text


def _conforms_atom(tname, trait):
    return ('conforms', tname, trait)


def _is_copyable_trait(trait):
    return _as_str(trait) in ('Copyable',)


def _is_movable_trait(trait):
    return _as_str(trait) in ('Movable',)


def _atom_implied_by_assumptions(atom, assumptions, trait_bases, cache):
    """Whether `atom` is implied by `assumptions` (all assumed true)."""
    if atom is None:
        return False
    ak = atom[0]
    if ak == 'and':
        return (_atom_implied_by_assumptions(atom[1], assumptions, trait_bases, cache)
                and _atom_implied_by_assumptions(atom[2], assumptions, trait_bases, cache))
    if ak == 'or':
        # atom implied if either disjunct implied? no: (x or y) as a goal is implied
        # if x implied or y implied.
        return (_atom_implied_by_assumptions(atom[1], assumptions, trait_bases, cache)
                or _atom_implied_by_assumptions(atom[2], assumptions, trait_bases, cache))
    if ak == 'conforms':
        for a in assumptions:
            if _atom_implies(a, atom, trait_bases, cache):
                return True
        return False
    if ak == 'not':
        # implied if assumptions prove the negation: e.g. assume not X.
        for a in assumptions:
            if _atom_implies(a, atom, trait_bases, cache):
                return True
        # or if inner is disproved? conservative: only direct implication.
        return False
    return False


def _text_implied_by_text(goal_text, assume_text, trait_bases, cache):
    if not goal_text:
        return True
    # Treat empty/absent assumption as unconditional (no assumptions) only when
    # goal is also empty; otherwise cannot prove from nothing.
    g = _constraint_atoms(_parse_constraint_expr(goal_text))
    a = _constraint_atoms(_parse_constraint_expr(assume_text)) if assume_text else None
    if g is None:
        # Unknown goal: conservative accept.
        return True
    if a is None:
        if assume_text:
            # Unparseable assumption: conservative accept.
            return True
        assumptions = []
    else:
        # Flatten top-level ands into assumptions.
        assumptions = []
        stack = [a]
        while stack:
            cur = stack.pop()
            if cur is None:
                continue
            if cur[0] == 'and':
                stack.append(cur[1])
                stack.append(cur[2])
            else:
                assumptions.append(cur)
    return _atom_implied_by_assumptions(g, assumptions, trait_bases, cache)


def _struct_field_defs(sd):
    out = []
    for f in (getattr(sd, 'fields', None) or []):
        if not hasattr(f, 'name'):
            continue
        name = _as_str(getattr(f, 'name', ''))
        if not name or ',' in name:
            continue
        t = _ann_to_str(getattr(f, 'type_ann', None))
        if not t:
            continue
        line = getattr(f, 'line', 0) or getattr(sd, 'line', 0) or 0
        out.append((name, t, line))
    return out


def _field_copy_move_problem(enclosing, fname, ftype_text, want_trait, struct_map, trait_bases, cache):
    """Return (problem, reason_kind) or None if ok/unknown-accept.

    want_trait: 'Copyable' or 'Movable'.
    """
    # Resolve field type
    base, targs = _parse_type_app(ftype_text)
    if not base:
        return None
    enc_params = set(_sd_bracket_param_names(enclosing))
    enc_bc = _sd_base_constraints_map(enclosing)
    enc_assume = enc_bc.get(want_trait, '')
    # If enclosing doesn't declare this trait, synthesis check not applicable.
    if want_trait not in enc_bc:
        return None

    # If base is a type parameter of enclosing struct
    if base in enc_params and not targs:
        goal = f"conforms_to({base}, {want_trait})"
        if _text_implied_by_text(goal, enc_assume, trait_bases, cache):
            return None
        # Not provable: for synthesis, an unprovable requirement blocks.
        # But be careful not to invent diagnostics for genuinely unknown cases
        # outside scope. For type params, this is the OR/multi-field class.
        return ('param', goal)

    fdef = struct_map.get(base)
    if fdef is None:
        # Unknown/imported type: accept.
        return None
    f_bc = _sd_base_constraints_map(fdef)
    if want_trait not in f_bc:
        # Field type has no Copyable/Movable conformance at all: out of scope.
        return None
    f_need = f_bc.get(want_trait, '')
    if not f_need:
        # Field type's conformance is unconditional: fine.
        return None

    # Field type has conditional conformance. Determine if enclosing implies it
    # for this declared field instantiation.
    fparams = _sd_bracket_param_names(fdef)
    needed = f_need

    # Variadic pack: a single type parameter used as `P.all_conforms_to[Trait]()`
    # applies to all supplied type arguments. Expand before substitution.
    _expanded_pack = False
    if targs and fparams:
        # Try any single param name as pack if condition has all_conforms_to.
        for p in fparams:
            m = re.search(rf'\b{re.escape(p)}\.all_conforms_to\[([A-Za-z_]\w*)\]\s*\(\s*\)', f_need)
            if m and (len(fparams) == 1 or len(targs) != len(fparams)):
                tr = m.group(1)
                parts = [f"conforms_to({a.strip()}, {tr})" for a in targs if _as_str(a).strip()]
                if parts:
                    needed = ' and '.join(f'({p2})' for p2 in parts)
                    _expanded_pack = True
                break

    if not _expanded_pack:
        subs = {}
        if targs and fparams:
            for i, p in enumerate(fparams):
                if i < len(targs):
                    subs[p] = targs[i]
        needed = _subst_constraint_text(f_need, subs) if subs else f_need

    # If needed text contains unknown constructs, be conservative accept.
    if 'all_conforms_to' in needed or 'each ' in needed:
        return None

    # Determine if needed is implied by enclosing assumptions for want_trait.
    # Also treat enclosing unconditional (empty assume) as "no assumptions".
    # OR-gated enclosing constraint is not definite enough: for synthesis we need
    # the requirement provable; _text_implied_by_text treats unparseable/empty
    # appropriately, but OR in assumption means not all disjuncts hold.
    # Our _text_implied_by_text checks goal implied by assumptions (flattened ands);
    # an assumption that is itself an OR does not imply its disjuncts, which is correct.
    if _text_implied_by_text(needed, enc_assume, trait_bases, cache):
        return None

    # Not implied. But "genuinely non-copyable field type (no Copyable conformance at all)
    # is out of scope..." - we already filtered that. A conditional conformance that can't
    # be proven satisfied is a synthesis problem.
    return ('cond', needed)


def check_copy_move_synthesis(struct_defs, trait_defs):
    """Declaration-time synthesized copy/move constructor diagnostics (part 4)."""
    trait_bases = {}
    for td in (trait_defs or []):
        if isinstance(td, TraitDef):
            trait_bases[_as_str(getattr(td, 'name', ''))] = list(getattr(td, 'bases', []) or [])
    struct_map = {}
    for sd in (struct_defs or []):
        if isinstance(sd, StructDef):
            struct_map[_as_str(getattr(sd, 'name', ''))] = sd
    cache = {}
    errors = []

    for sd in (struct_defs or []):
        if not isinstance(sd, StructDef):
            continue
        bc = _sd_base_constraints_map(sd)
        for want_trait, kind, msg_tail in (
            ('Copyable', 'copy', "has non-copyable type"),
            ('Movable', 'move', "has non-movable and non-implicitly-copyable type"),
        ):
            if want_trait not in bc:
                continue
            for fname, ftype, fline in _struct_field_defs(sd):
                prob = _field_copy_move_problem(sd, fname, ftype, want_trait, struct_map, trait_bases, cache)
                if prob is None:
                    continue
                errors.append((fline or getattr(sd, 'line', 0) or 0,
                    f"cannot synthesize {kind} constructor because field '{fname}' {msg_tail}"))
                # one error per struct/trait is enough? modular shows per field; but
                # report first deterministically.
                break
            if errors:
                break
        if errors:
            break

    if errors:
        line, msg = sorted(errors, key=lambda x: x[0])[0]
        raise RuntimeError(f"error: {msg}")


def _split_where_message(expr):
    """`(cond, "message")` -> (cond, message); any other clause -> (expr, None)."""
    if (isinstance(expr, TupleExpr) and len(expr.elements) == 2
            and isinstance(expr.elements[1], StringLiteral)):
        return expr.elements[0], expr.elements[1].value
    return expr, None


def _where_bindings(targs: dict) -> dict:
    """The comptime bindings a clause folds against: a concrete integer, float,
    or Bool type argument. Any other argument is left out, so a clause over it
    is undecided rather than wrong."""
    bindings = {}
    for name, conc in targs.items():
        text = str(conc).strip()
        if re.fullmatch(r'-?\d+', text):
            bindings[name] = int(text)
        elif re.fullmatch(r'-?\d+\.\d+([eE][-+]?\d+)?', text):
            bindings[name] = float(text)
        elif text in ('True', 'False'):
            bindings[name] = (text == 'True')
    return bindings


def _module_alias_bindings(module_src: str) -> dict:
    """Fold top-level `alias NAME = <literal>` bindings from module text.

    The parser records `alias` as a no-op ExprStmt and the binding as an
    ordinary AssignStmt, so the AST cannot distinguish a module alias from a
    module-level assignment. Scan the source for `alias NAME = <literal>`
    lines instead and fold the literal with the shared constant folder. The
    last binding for a repeated name wins; anything that does not fold stays
    out so the clause remains undecided rather than wrong."""
    bindings = {}
    if not module_src:
        return bindings
    for line in module_src.splitlines():
        m = re.match(r'^alias\s+([A-Za-z_]\w*)\s*=\s*(.+)$', line)
        if not m:
            continue
        name, rhs = m.group(1), m.group(2).strip()
        try:
            node = Parser(py_tokenize(rhs))._parse_expr(0)
            val = eval_const(node, {})
        except Exception:
            val = None
        if isinstance(val, (bool, int, float, str)):
            bindings[name] = val
    return bindings


def _where_conformance_bases(module_src: str) -> dict:
    """Declared struct/trait bases from module_src for conforms_to folding."""
    bases = {}
    try:
        stmts = Parser(py_tokenize(textwrap.dedent(module_src or ''))).parse_module()
    except Exception:
        stmts = []
    for s in stmts:
        if isinstance(s, (StructDef, TraitDef)):
            name = getattr(s, 'name', None)
            if isinstance(name, str):
                bases[name] = list(getattr(s, 'bases', None) or [])
    # TraitDef AST nodes do not currently carry parent traits; extract them from
    # source text so trait-to-trait conformance is visible.
    try:
        src = module_src or ''
        for m in re.finditer(r'^\s*trait\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*\(([^)]*)\)\s*:', src, re.MULTILINE):
            name = m.group(1)
            bstr = m.group(3) or ''
            blist = []
            for part in bstr.split(','):
                part = part.strip()
                if not part:
                    continue
                b = part.split('[')[0].split('.')[-1].strip()
                if b and re.match(r'^[A-Za-z_]\w*$', b):
                    blist.append(b)
            if blist or name not in bases:
                bases[name] = blist
        for m in re.finditer(r'^\s*trait\s+([A-Za-z_]\w*)\b', src, re.MULTILINE):
            bases.setdefault(m.group(1), [])
    except Exception:
        pass
    return bases


def _where_conforms_to_pred(module_src: str, targs: dict):
    bases = _where_conformance_bases(module_src)
    if not bases:
        return None
    def _resolve_name(n):
        # Map a generic parameter name to its concrete type arg when known.
        if isinstance(n, str) and n in targs:
            c = str(targs[n]).strip()
            # strip simple qualifiers/generics to base name for lookup
            c = c.split('.')[-1]
            if '[' in c:
                c = c.split('[', 1)[0]
            return c
        return n
    def pred(tname, trname):
        return conforms_to(_resolve_name(tname), _resolve_name(trname), bases)
    return pred


def check_where_clauses(module_src: str, template_src: str, targs: dict):
    """Enforce the template's `where` clauses for the concrete `targs`.

    Each clause is folded by the shared constant folder
    (mojo.middle.comptime.eval_const_bool_state): a provably false clause raises
    ConformanceError with its message, or its source when it has none. A true
    clause passes. An undecided clause (a name the folder cannot resolve, such
    as a comptime assert proved elsewhere in the body) is accepted as before.
    The regex checks for `T.is_floating_point()` / `is_integral()` / `T == U`
    only run for a template the parser cannot read or whose clause the folder
    could not decide, so DType predicates keep their existing result."""
    clauses = _template_where_clauses(template_src)
    undecided = clauses is None
    if clauses:
        src_texts = _header_where_texts(template_src)
        bindings = _module_alias_bindings(module_src)
        bindings.update(_where_bindings(targs))
        _cpred = _where_conforms_to_pred(module_src, targs)
        for i, item in enumerate(clauses):
            cond, msg = _split_where_message(item)
            state = eval_const_bool_state(cond, bindings, conforms_to_pred=_cpred)
            if state == CONST_FALSE:
                if msg is not None:
                    raise WhereConformanceError(msg)
                text = (src_texts[i] if len(src_texts) == len(clauses)
                        else ' and '.join(src_texts))
                raise WhereConformanceError(f"requirement '{text}' is not satisfied")
            if state != CONST_TRUE:
                undecided = True
    if undecided:
        _check_where_text_predicates(template_src, targs)


def _check_where_text_predicates(template_src: str, targs: dict):
    """The DType / type-equality where checks, by regex over the clause text."""
    for m in re.finditer(r'where\s+(.+?)(?::|\n|$)', template_src):
        clause = m.group(1).strip()
        # Check for X.is_floating_point()
        for mp in re.finditer(r'([A-Za-z_][A-Za-z0-9_]*)\.is_floating_point\s*\(\s*\)', clause):
            pname = mp.group(1)
            if pname in targs:
                conc = targs[pname]
                if not _is_float_dtype(conc):
                    raise ConformanceError(
                        f"type '{conc}' does not satisfy constraint "
                        f"'{clause}' (required by parameter '{pname}')")
        # Check for X.is_integral()
        for mp in re.finditer(r'([A-Za-z_][A-Za-z0-9_]*)\.is_integral\s*\(\s*\)', clause):
            pname = mp.group(1)
            if pname in targs:
                conc = targs[pname]
                if _is_float_dtype(conc):
                    raise ConformanceError(
                        f"type '{conc}' does not satisfy constraint "
                        f"'{clause}' (required by parameter '{pname}')")
        # Check for X.is_signed()/is_unsigned() etc if needed
        # Check for X == Y (type-equality constraint, e.g. `where T == Int`)
        for mp in re.finditer(r'([A-Za-z_][A-Za-z0-9_]*)\s*==\s*([A-Za-z_][A-Za-z0-9_]*)', clause):
            pname, other = mp.group(1), mp.group(2)
            if pname in targs:
                conc = targs[pname].split('.')[-1].strip()
                if conc != other:
                    raise ConformanceError(
                        f"type '{targs[pname]}' does not satisfy constraint "
                        f"'{clause}' (required by parameter '{pname}')")


def check_bounds(module_src: str, template_src: str, targs: dict):
    """Verify each concrete type arg satisfies its parameter's trait bound.
    Raises ConformanceError (a clear compile error) on the first violation."""
    bounds = parse_bounds(template_src)
    for pname, conc in targs.items():
        bound = bounds.get(pname)
        if not bound:
            continue
        ok, missing = check_conformance(module_src, conc, bound)
        if not ok:
            why = '; '.join(missing)
            raise ConformanceError(
                f"type '{conc}' does not conform to trait '{bound}' "
                f"(required by parameter '{pname}'): {why}")
    # Also check where clause constraints
    try:
        check_where_clauses(module_src, template_src, targs)
    except ConformanceError:
        raise
    except Exception:
        pass


def extract_struct_source(module_src: str, name: str):
    """Pull the source text of a `struct name[...]: ...` block, by indentation."""
    lines = module_src.splitlines(keepends=True)
    pat = re.compile(rf'^(\s*)struct\s+{re.escape(name)}\s*[\[\(:]')
    start = None
    for i, l in enumerate(lines):
        if pat.match(l):
            start = i
            break
    if start is None:
        return None
    base = len(lines[start]) - len(lines[start].lstrip())
    depths = _bracket_depth_by_line(module_src)
    end = _find_block_end(lines, depths, start, base)
    return ''.join(lines[start:end])


# Reverse of the ABI type map, for inferring a generic's type args from the C
# types of its call arguments (slice 2). We substitute the Mojo name into the
# template source, so we need the Mojo spelling, not the C type.
_C_TO_MOJO = {
    'int64_t': 'Int64', 'int32_t': 'Int32', 'int16_t': 'Int16', 'int8_t': 'Int8',
    'int': 'Int', 'uint64_t': 'UInt64', 'uint32_t': 'UInt32', 'uint16_t': 'UInt16',
    'uint8_t': 'UInt8', 'unsigned int': 'UInt', '_Bool': 'Bool',
    'double': 'Float64', 'float': 'Float32', '__fp16': 'Float16', 'char *': 'String',
}


def c_to_mojo(ctype: str):
    """The Mojo spelling of a C argument type, or None when the C type does not
    name one. There is deliberately NO default: a struct, a pointer or an erased
    SIMD value has a C type this table does not list, and answering `Int` for it
    bound a type parameter to a type the argument is not. That binding then
    reached `check_bounds`, which rejected it (`dtype := Int64` for an erased
    `SIMD[.float32, 2]`), so a guess was reported as a user error."""
    return _C_TO_MOJO.get(ctype)


def inferred_ctype_is_specific(ctype) -> bool:
    """True when `ctype` NAMES the argument's Mojo type, rather than being a
    placeholder this codegen substituted for a type it did not compute.

    Deliberately not every key of `_C_TO_MOJO`: `int64_t` and `int` are this
    codegen's UNIVERSAL scalar fallbacks — every SIMD value, every `Array`/
    `Span` element whose element type was not tracked, every opaque
    construction and every unknown subscript lowers to `int64_t` — so the C
    spelling cannot tell a genuine Int argument from an erased one. Any C
    type absent from `_C_TO_MOJO` (`char`, a bare `Foo *`) reaches
    `c_to_mojo`, which now answers None for it (no `Int` default), for the same reason."""
    return ctype in _C_TO_MOJO and ctype not in ('int64_t', 'int')

_SCALAR_ANN_RE = re.compile(r'^Scalar\[\s*([^,\[\]]+)\s*\]$')
_SIMD_ANN_RE = re.compile(r'^SIMD\[\s*([^,\[\]]+)\s*(?:,\s*([^,\[\]]+)\s*)?\]$')


def _unify_param_ann(ann, pnames, arg_ctype) -> dict:
    """{type-param: concrete value} from unifying ONE parameter's declared type
    annotation against ONE argument's actual C type, or `{}` when the shape is
    not one we can prove.

    Two shapes, both provable rather than guessed:

    * the annotation IS the type parameter (`x: T`) — what this function always
      did, kept verbatim;
    * the annotation wraps it: `x: SIMD[dtype, width]`. The numeric library is
      written entirely this way (`def copysign[dtype, width](magnitude:
      SIMD[dtype,width], sign: SIMD[dtype,width]) -> SIMD[dtype,width]`), and
      the equality test this replaces could never bind `dtype` or `width`, so
      every such template was declined and its call sites reached the generated
      C as bare externs.

    The `SIMD[...]` and `Scalar[...]` shapes bind only from a scalar C type.
    This codegen erases SIMD outright (`_mojo_type('SIMD[Float64, 4]')` is
    `int64_t`, and `Scalar[DType.int32]` is `int64_t` too), so an `int64_t`
    argument is ambiguous: `erf(SIMD[.float32, 2](2))` and `erf(Int64(2))` have
    the same C type, and binding `dtype := Int64` from it was a guess that the
    constraint check now rejects. That case binds nothing and the template is
    declined as unbound. Any other scalar C type (`double`, `float`, `int32_t`)
    cannot be an erased SIMD, so the argument is that scalar, `SIMD[dtype, 1]`,
    and `dtype` and `width` bind from it. Recovering the dtype of a wider SIMD
    needs the argument's declared type, not its C type.

    Anything else — a nested `Pointer[T]`, `Some[T]`, a param used only as a
    comptime argument, an annotation that is not a string — returns `{}`, so
    `infer_type_args` keeps declining it exactly as before. The all-params-bound
    requirement below is what makes that safe: a partially-understood shape
    binds nothing.

    (`Pointer[T]` is genuinely out of reach here and deliberately so: the
    argument's C type for a pointer is `Foo *`, and which `Foo` it points at is
    what we would be inferring, not what the annotation tells us. Guessing from
    the pointee spelling would be a guess.)"""
    if not isinstance(ann, str):
        return {}
    ann = ann.strip()
    # Inside a struct (or one of its methods), `Self.T` IS the enclosing
    # type's own name for the bracket parameter `T` — which is exactly how
    # `monomorphize_source` substitutes it, `\bSelf\.<param>\b` in a pass of
    # its own. Reading it as anything else here made every template whose
    # parameter annotation is written `Self.T` unbindable while its
    # SUBSTITUTED form was perfectly fine, i.e. the inference and the
    # substitution disagreed about the same text. The stdlib writes it that way
    # throughout (`FormatStruct[T, o]`'s `__init__(out self, ref[Self.o]
    # writer: Self.T, ...)`, `Pointer[Self.T, Self.o]`).
    if ann.startswith('Self.'):
        ann = ann[5:]
    if ann in pnames:
        bound = c_to_mojo(arg_ctype)
        return {} if bound is None else {ann: bound}
    # `Scalar[dtype]` and `SIMD[dtype, width]`. SIMD is erased to `int64_t`, so
    # an `int64_t` argument may be ANY SIMD value or a plain Int64: it binds
    # nothing. Any other scalar C type (`double`, `float`, `int32_t`) cannot be
    # an erased SIMD, so the argument IS that scalar, which is `SIMD[dtype, 1]`.
    if arg_ctype == 'int64_t':
        return {}
    dtype = c_to_mojo(arg_ctype)
    if dtype is None:
        return {}
    m = _SCALAR_ANN_RE.match(ann)
    if m and m.group(1) in pnames:
        return {m.group(1): dtype}
    m = _SIMD_ANN_RE.match(ann)
    if m and m.group(1) in pnames:
        out = {m.group(1): dtype}
        if m.group(2) is not None:
            if m.group(2) not in pnames:
                return {}
            out[m.group(2)] = '1'
        return out
    return {}


# ── Parameters this codegen erases ──────────────────────────────────────
#
# A bracket parameter that occurs ONLY in positions `_mojo_type` discards can be
# given any concrete name without changing a byte of the artifact, so binding it
# is provably output-equivalent rather than a guess — and leaving it unbound
# refuses templates whose own annotations determine everything the artifact
# actually depends on (`FormatStruct[T, o]`, the stdlib's struct-formatting
# helper, is 15 of the 108 real undefined-call sites on its own).
#
# Measured (`gimple_codegen._mojo_type`, the single resolver both
# `_struct_layout_anns` and the codegen's own annotations go through):
#
#     Pointer[Formatter, MutOrigin] -> 'int64_t *'   Ref[Formatter, MutOrigin] -> 'int64_t'
#     Pointer[Formatter, Int64]     -> 'int64_t *'   Ref[Formatter, Int64]     -> 'int64_t'
#     Pointer[Formatter, __junk__]  -> 'int64_t *'   MutOrigin                  -> 'int64_t'
#
# A pointer/reference's SECOND argument is discarded outright, and a bare origin
# type reduces like any other unknown type. The two spellings that reach those
# positions are the `ref[...]`/`mut[...]`/`inout[...]`/`owned[...]`/
# `borrowed[...]` qualifier on a parameter, and any argument of `Pointer[`/
# `Ref[`/`UnsafePointer[` after the first.
ERASED_TYPE_ARG = 'MutOrigin'
_ERASED_QUALIFIER_RE = re.compile(
    r'\b(?:ref|mut|inout|owned|borrowed)\s*\[\s*(?:Self\s*\.\s*)?(\w+)')
# The COMMA inside the bracket is load-bearing: without it this would match the
# FIRST argument too, and the pointee is exactly the argument that decides
# whether the field is `int64_t *` or `int64_t`.
_ERASED_PTR_TAIL_RE = re.compile(
    r'\b(?:Pointer|Ref|UnsafePointer)\s*\[[^][]*,[^][]*?\b(?:Self\s*\.\s*)?(\w+)')


def _code_only(template_src: str) -> str:
    """`template_src` with the generic's own `[...]` head, every docstring and
    every `#` comment removed — so `erased_only_params` counts only the places
    the name appears in CODE.

    Without this the head declaration itself disqualifies every parameter
    (`struct FormatStruct[T: Writer, o: MutOrigin]` mentions `o`), and so does
    the stdlib's own docstring for it (`o: The mutable origin of the writer.`)
    — prose about the parameter is not a use of it, and counting prose would
    make the erased-only proof unreachable for exactly the templates it is
    meant to cover. Character-level rather than line-based so a `#` inside a
    string cannot truncate the rest of the file, the same hazard
    `_bracket_depth_by_line` documents."""
    s = re.sub(r'"""[\s\S]*?"""', ' ', template_src)
    s = re.sub(r"'''[\s\S]*?'''", ' ', s)
    s = re.sub(r'(?m)#.*$', ' ', s)
    m = mm.head_match(s)
    if m:
        s = s[:m.start()] + ' ' * (m.end() - m.start()) + s[m.end():]
    return s


def erased_only_params(template_src: str, params) -> set:
    """The subset of `params` that occurs ONLY in positions `_mojo_type`
    discards — see `ERASED_TYPE_ARG`. Empty if there are none.

    COUNTED over CODE only (`_code_only`), not pattern-matched-and-assumed: a
    parameter qualifies only when EVERY occurrence of its name falls inside an
    erased span. `FormatStruct[T, o]`'s `o` qualifies — its two code
    occurrences are the `Pointer[Self.T, Self.o]` field and the `ref[Self.o]
    writer` qualifier — while its `T` does not, being the pointee."""
    src = _code_only(template_src)
    spans = [m.span(1) for r in (_ERASED_QUALIFIER_RE, _ERASED_PTR_TAIL_RE)
             for m in r.finditer(src)]
    if not spans:
        return set()
    out = set()
    for p in params:
        # Match the BARE name, not `Self.<name>`: the erased spans are the
        # captured parameter itself, so `Self.o`'s occurrence has to be the `o`
        # inside it for the containment test below to mean anything.
        occ = [m.span() for m in re.finditer(rf'\b{re.escape(p)}\b', src)]
        if occ and all(any(a <= s and e <= b for a, b in spans) for s, e in occ):
            out.add(p)
    return out


def phantom_type_params(template_src: str, params) -> set:
    """The subset of `params` that occurs NOWHERE outside the generic head.

    A phantom parameter is a type parameter the declaration names but never
    mentions again — not in a field's type, not in a method's signature, not in
    a method body, not in a `comptime` alias.  It is a strictly stronger
    condition than `erased_only_params`' "only in positions `_mojo_type`
    discards": a phantom parameter has no occurrence to discard, and
    `erased_only_params` deliberately requires `occ` to be non-empty, so it
    returns the EMPTY set for one.  That gap is why this is a second predicate
    rather than a reuse: `struct Marker[T: AnyType]: var v: Int` is exactly the
    shape `erased_only_params` declines and `formal/monomorph.py`'s
    `without_template_bodies` needs the answer for (it decides whether such a
    template's declaration is already a concrete one and must not be dropped).

    COUNTED over `_code_only`, which removes the head's own `[...]`, every
    docstring and every comment — so the declared name in the head and prose
    about the parameter are not uses of it, exactly as for
    `erased_only_params`."""
    src = _code_only(template_src)
    out = set()
    for p in params:
        if not re.search(rf'\b{re.escape(p)}\b', src):
            out.add(p)
    return out


def _fill_erased_params(template_src, params, binding) -> dict:
    """`binding` plus `ERASED_TYPE_ARG` for every still-unbound parameter that
    `erased_only_params` proves is discarded. An unbound parameter that is NOT
    erased-only is left unbound, so the caller's all-params-bound requirement
    still declines it exactly as before."""
    missing = [p for p in params if p not in binding]
    if not missing:
        return binding
    erased = erased_only_params(template_src, params)
    for p in missing:
        if p in erased:
            binding[p] = ERASED_TYPE_ARG
    return binding


def infer_type_args(template_src: str, arg_ctypes):
    """Infer a generic's type args from the C types of its call arguments. For
    each type parameter that appears in a parameter's type ANNOTATION, bind it
    to the Mojo type of the matching argument (`_unify_param_ann` says which
    annotation shapes that covers). Returns the ordered list of Mojo type
    names, or None if any parameter is unbound."""
    params = type_param_names(template_src)
    if not params:
        return None
    fn = None
    for s in Parser(py_tokenize(template_src)).parse_module():
        if isinstance(s, FunctionDef):
            fn = s
            break
    if fn is None:
        return None
    binding = {}
    for i, (_pname, ann) in enumerate(fn.params):
        if i >= len(arg_ctypes):
            break
        for k, v in _unify_param_ann(ann, params, arg_ctypes[i]).items():
            binding.setdefault(k, v)
    binding = _fill_erased_params(template_src, params, binding)
    # A parameter no argument binds but the template DEFAULTS
    # (`def pick[result_type: AnyType = NoneType](x: Int)`, called as
    # `pick(10)`) takes its default, exactly as Mojo does when the caller
    # omits it. Left unbound, `pick(10)` declined here, its call site fell
    # through to a bare `pick` with no definition anywhere, and the program
    # printed the weak "unavailable in compiled mode" stub. This is the
    # same provable-default rule `infer_struct_type_args(fill_defaults=True)`
    # applies to constructors, and `elab_intu`'s in-TU seed reaches this
    # function too, so the definition and the call site agree on one
    # instantiation.
    _defaults = type_param_defaults(template_src)
    for p in params:
        if p not in binding:
            _d = _default_type_arg(_defaults.get(p, ''))
            if _d is not None:
                binding[p] = _d
    if any(p not in binding for p in params):
        return None
    return [binding[p] for p in params]


def infer_struct_type_args(module_src: str, struct_name: str, arg_ctypes,
                           fill_defaults: bool = False):
    """Type args for a `Struct(...)` CONSTRUCTOR call from that call's argument
    C types, or None if they cannot all be bound.

    Mojo spells `FormatStruct(writer, "Slice")` with NO bracket arguments far
    more often than `FormatStruct[Writer, origin](...)`, and the constructor is
    where the types are actually written:

        struct FormatStruct[T: Writer, o: MutOrigin](Movable):
            def __init__(out self, ref[Self.o] writer: Self.T, name: StaticString)

    `_elaborate_generic_struct_call` only ever fired on a `SubscriptExpr`
    callee, so every bare `Struct(...)` construction of an imported generic
    struct fell through to the ordinary call path and emitted a bare
    `FormatStruct (writer, _t2);` — a call to a symbol nothing defines. That
    single shape was 56 of the 108 real undefined-call sites measured over the
    stdlib sweep (see
    `bugs/imported-generic-elaboration-defect`).

    Every candidate `__init__` whose arity matches is tried, and the type args
    must agree across all of them that bind: a struct with two constructors
    that infer DIFFERENT `T`s from the same call is ambiguous, and ambiguity is
    refused rather than resolved by preferring the first — the same rule
    `myinterpreter.MojoOverloadSet` states for parameter types it cannot use."""
    # The TEMPLATE for the `[...]` head, the MODULE for the struct's methods.
    # `type_param_names` and `erased_only_params` both read the head, and
    # `head_match` finds the FIRST generic in the text it is given — which for
    # a module like `std/format/_utils.mojo` is some other struct entirely.
    # `erased_only_params` additionally needs the whole struct body, which is
    # exactly the template.
    tmpl = extract_struct_source(module_src, struct_name)
    params = type_param_names(tmpl) if tmpl else []
    if not params:
        return None
    ctors = []
    for s in Parser(py_tokenize(module_src)).parse_module():
        if not (isinstance(s, StructDef) and s.name == struct_name):
            continue
        ctors = [m for m in getattr(s, 'methods', [])
                 if m.name == '__init__' or m.name.startswith('__init__')]
        break
    resolved = []
    # PART 6 (2026-10-23, family D piece 2): `fill_defaults` fills the
    # still-unbound bracket parameters from their OWN provable defaults
    # (`_default_type_arg` — a literal or a leading-uppercase type name),
    # not only the erased-only ones `_fill_erased_params` covers. Measured
    # on test_utils' `CopyCounter(1)`: its `trivial_copy: Bool = False`
    # VALUE parameter occurs in a comptime field (not an erased span), so
    # the erased-only fill leaves it unbound and EVERY overload that binds
    # `T` from the argument is refused — the call reaches the generated C
    # as a declared-never-defined mangled factory (the zero-stub hazard
    # class). The elab_intu seed passes True; the `.o` route's caller keeps
    # the default False (its strict refusal is what elab_intu's in-TU
    # materialization exists to take over, and widening it here would
    # double-define what the seed already owns).
    _d2_defaults = (type_param_defaults(tmpl) if fill_defaults else {})
    for ctor in ctors:
        anns = [ann for pn, ann in ctor.params
                if pn != 'self' and not pn.startswith('*')]
        if len(anns) != len(arg_ctypes):
            continue
        binding = {}
        for ann, ct in zip(anns, arg_ctypes):
            for k, v in _unify_param_ann(ann, params, ct).items():
                binding.setdefault(k, v)
        # A fill_defaults-mode constructor earns a VOTE only when it bound at
        # least one parameter FROM THE CALL itself. CopyCounter's copy ctor
        # (`copy: Self`) unifies nothing; default-fill would bind T to its
        # `= NoneType` default and trivial_copy to `False`, voting
        # ['NoneType', 'False'] against the value ctor's argument-derived
        # ['Int', 'False'] — the agreement rule then refuses the whole call
        # as ambiguous, even though no ambiguity exists: a constructor that
        # inferred nothing from the argument is not an inference. Strict
        # mode (fill_defaults off) never reaches the fill loop, so its votes
        # are unchanged.
        _unify_bound = len(binding)
        if _d2_defaults and _unify_bound == 0:
            continue
        binding = _fill_erased_params(tmpl, params, binding)
        if _d2_defaults:
            for _p in params:
                if _p not in binding:
                    _d = _default_type_arg(_d2_defaults.get(_p, ''))
                    if _d is not None:
                        binding[_p] = _d
        if any(p not in binding for p in params):
            continue
        resolved.append([binding[p] for p in params])
    if not resolved or any(r != resolved[0] for r in resolved[1:]):
        return None
    return resolved[0]


def _struct_layout(concrete_src: str, name: str):
    """(fields, methods) of the monomorphized struct: fields as (name, c_type),
    methods as (name, ret_ctype, [param_ctypes excluding self])."""
    fields, methods, _anns = _struct_layout_anns(concrete_src, name)
    return fields, methods


def _struct_layout_anns(concrete_src: str, name: str):
    """(fields, methods, annotations) of the monomorphized struct.

    `annotations` is `[(field_name, raw_mojo_annotation), (method_name,
    'ret'|'param', index, raw_annotation)]` — the UNRESOLVED Mojo text of
    every field and method type, which `fields`/`methods` then reduce to a
    ctype through the stateless `_mojo_type`.

    It is published because those two reductions are the wrong place to
    finish the job and the caller is the only place that can: a field
    annotated with a GENERIC STRUCT's own instantiation (`Wrapper[
    Inner[int64_t]]._inner: Inner[int64_t]`) means "a pointer to the
    concrete `Inner_int64_t`", which needs (a) that instantiation
    materialized so its name and layout exist at all, and (b) the CALLER's
    `struct_field_types` registry to resolve the name against — neither of
    which a module-level `_mojo_type` can see, so it answers `int64_t` and
    the field is silently boxed. See
    `mojo/backend_gimple/emit_resolve.py::_ensure_generic_struct`, the one
    caller that publishes this."""
    fields = []
    methods = []
    anns = []
    for s in Parser(py_tokenize(concrete_src)).parse_module():
        if not (isinstance(s, StructDef) and s.name == name):
            continue
        for f in getattr(s, 'fields', []):
            # `fields` is VarDecl + AssignStmt (fire_compiler._parse_struct's
            # own contract), and ONLY VarDecl has a `.name`:
            #
            # * a dataclass field with a default, `name: Type = default`
            #   spelled WITHOUT `var`, is an AssignStmt CARRYING the
            #   annotation — a real field, its name on `.target`;
            # * a struct-level assignment the parser could not place any
            #   better is an AssignStmt whose target is not a name (no
            #   annotation, no provable layout) — not a field at all.
            #
            # Reading `.name`/`.type_ann` off both, as before, died with
            # AttributeError on the second kind — the measured instance is
            # the stdlib containers' `comptime IteratorOwnedType: Iterator
            # where conforms_to(...) = ...` aliases, whose `where`-clause
            # continuation the parser used to drop and re-parse as an
            # ordinary assignment (now a ComptimeVarStmt — see
            # fire_compiler._parse_comptime's own where-skip), so the junk
            # no longer reaches here; the narrowing is what keeps this
            # reader honest for either spelling.
            if isinstance(f, VarDecl):
                fields.append((f.name, _mojo_type(f.type_ann)))
                anns.append((f.name, 'field', 0, f.type_ann))
            elif (isinstance(f, AssignStmt) and isinstance(f.target, IdentExpr)
                    and f.type_ann is not None):
                fields.append((f.target.value, _mojo_type(f.type_ann)))
                anns.append((f.target.value, 'field', 0, f.type_ann))
        for m in getattr(s, 'methods', []):
            ret = _mojo_type(m.return_type) if m.return_type else 'void'
            ps = [_mojo_type(t) for n, t in m.params if n != 'self']
            methods.append((m.name, ret, ps))
            anns.append((m.name, 'ret', 0, m.return_type))
            _pi = 0
            for _pn, _pt in m.params:
                if _pn == 'self':
                    continue
                anns.append((m.name, 'param', _pi, _pt))
                _pi += 1
        break
    return fields, methods, anns


def _elab_signature(concrete_src: str, name: str):
    """(ret_ctype, [param_ctypes]) of the monomorphized function, via the ABI map."""
    for s in Parser(py_tokenize(concrete_src)).parse_module():
        if isinstance(s, FunctionDef) and s.name == name:
            ret = _mojo_type(s.return_type) if s.return_type else 'void'
            if (isinstance(ret, str) and ret.startswith('MojoTuple_')
                    and not _body_builds_struct_tuple(
                            getattr(s, 'body', None))):
                # The SAME body-sensitive decision the defining unit's own
                # resolution makes (module_gen's all-functions loop and
                # emit_funcs' free-function path): a `-> Tuple[...]` return
                # whose body builds the tuple as a RUNTIME (list-backed)
                # tuple literal returns `MojoList *`, not the synthesized
                # by-value struct — without this the CALLER's extern and
                # call-site temps disagree with the instance TU's own
                # `MojoList *` prototype (measured 2026-10-21 part 4
                # integration on `split`'s `-> Tuple[String, String]`).
                ret = 'MojoList *'
            return ret, [_mojo_type(t) for _, t in s.params]
    return 'int64_t', []


def _defined_symbols(obj: str) -> set:
    """External symbols DEFINED (not undefined) by an object file, via `nm`.

    This is how the elaborator learns what the instantiation TU actually NAMED
    its methods, instead of re-deriving the names — which is impossible, and
    was measured impossible (see the `FormatStruct` section of
    bugs/imported-generic-elaboration-defect:
    the erasure that makes two `fields` overloads look identical is the same
    erasure that destroys the function `overload_suffix_for` is computed from).

    Cached by object path: the CAS objects are content-addressed and immutable,
    so a path names exactly one symbol set forever. `nm` is the same tool
    `build_stdlib_dylib._defined_symbols` already depends on for the same job.

    An empty set means "could not read them" as well as "defines nothing"; both
    make the caller fall back to what it did before, which is why the caller
    must treat it as advisory rather than as proof."""
    if obj in _SYMBOLS_CACHE:
        return _SYMBOLS_CACHE[obj]
    syms: set = set()
    try:
        out = subprocess.run(['nm', '-g', obj], capture_output=True,
                             text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            # Defined external: "<addr> <TYPE> <name>"; undefined: "<TYPE=U>
            # <name>". Uppercase type letter = external AND defined.
            if len(parts) >= 3 and parts[1] in ('T', 'D', 'S', 'B', 'C', 'I', 'R'):
                syms.add(parts[2])
    except Exception:
        syms = set()
    _SYMBOLS_CACHE[obj] = syms
    return syms


_SYMBOLS_CACHE: dict = {}


def _align_instantiation_error(struct_name, type_args, got):
    ta = ", ".join(str(a) for a in (type_args or []))
    if ta:
        head = f"function instantiation failed: {struct_name}[{ta}]"
    else:
        head = f"function instantiation failed: {struct_name}"
    return RuntimeError(
        f"{head}: @align struct alignment must be a positive power of 2, got {got}"
    )


def _align_instantiation_unknown(struct_name, type_args, name):
    ta = ", ".join(str(a) for a in (type_args or []))
    if ta:
        head = f"function instantiation failed: {struct_name}[{ta}]"
    else:
        head = f"function instantiation failed: {struct_name}"
    # Consistent with compiler unknown-declaration diagnostics.
    return RuntimeError(f"{head}: @align: use of unknown declaration '{name}'")


def _collect_module_int_bindings(module_src):
    bindings = {}
    try:
        mod = Parser(py_tokenize(module_src)).parse_module()
    except Exception:
        return bindings
    for stmt in mod:
        if isinstance(stmt, ComptimeVarStmt):
            try:
                v = _comptime.eval_const_int(stmt.value, bindings)
            except Exception:
                v = None
            if isinstance(v, int):
                bindings[stmt.target] = v
        elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
            # Module-level `alias X = 1` can be represented as an assignment in
            # some paths; capture integer-constant values when available.
            try:
                v = _comptime.eval_const_int(stmt.value, bindings)
            except Exception:
                v = None
            if isinstance(v, int):
                bindings[stmt.target.name] = v
    return bindings


def _find_struct_def_in_source(src, struct_name):
    try:
        mod = Parser(py_tokenize(src)).parse_module()
    except Exception:
        return None
    for stmt in mod:
        if isinstance(stmt, StructDef) and stmt.name == struct_name:
            return stmt
    return None


def _validate_generic_struct_align(module_src, tmpl_src, struct_name, type_args, targs):
    # Prefer the full module source so decorators attached above the struct are
    # visible; fall back to the extracted template.
    sd = _find_struct_def_in_source(module_src, struct_name)
    if sd is None:
        sd = _find_struct_def_in_source(tmpl_src, struct_name)
    if sd is None:
        return
    decs = getattr(sd, "decorators", None) or []
    # Build bindings: integer bracket args + module-level int aliases/comptimes.
    bindings = _collect_module_int_bindings(module_src)
    for k, v in (targs or {}).items():
        # Integer-like args are represented as strings (e.g. "3").
        try:
            iv = int(str(v).strip())
        except Exception:
            continue
        bindings[k] = iv
    for dec in decs:
        if not isinstance(dec, CallExpr):
            continue
        func = dec.func
        if not (isinstance(func, IdentExpr) and func.name == "align"):
            continue
        args = getattr(dec, "args", None) or []
        kwargs = getattr(dec, "kwargs", None) or []
        if len(args) != 1 or kwargs:
            continue
        arg = args[0]
        try:
            val = _comptime.eval_const_int(arg, bindings)
        except Exception:
            val = None
        if val is None:
            # Unknown name used in align expression: report user-visible error.
            if isinstance(arg, IdentExpr) and arg.name not in bindings:
                raise _align_instantiation_unknown(struct_name, type_args, arg.name)
            # Other non-constant/unknown cases: leave unknown and do not emit
            # a false diagnostic.
            continue
        err = align_value_error(val)
        if err is not None and "must be a positive power of 2" in err:
            raise _align_instantiation_error(struct_name, type_args, val)
        if err is not None:
            ta = ", ".join(str(a) for a in (type_args or []))
            head = f"function instantiation failed: {struct_name}[{ta}]" if ta else f"function instantiation failed: {struct_name}"
            raise RuntimeError(f"{head}: @align: {err.lstrip('@align ').strip()}")


class Elaborator:
    """Demand-driven, CAS-backed elaboration service."""

    def __init__(self, gcc=None):
        self.gcc = gcc

    def elaborate_generic_call(self, module_src: str, fn_name: str, type_args, arg_count: int | None = None,
                               arg_ctypes=None) -> dict:
        """Instantiate `fn_name` for `type_args` (a list of concrete type strings)
        via the CAS. Returns a dict {symbol, object, ret, params} or None.

        `arg_count` (the call's actual argument count, when known) disambiguates
        same-named generic overloads distinguished only by arity (e.g.
        itertools.product's 2/3/4-iterable versions) — see extract_fn_source.

        Elaborate-once-ever: the instantiation is content-addressed, so a repeat
        (here or in another program) is a cache hit."""
        tmpl = extract_fn_source(module_src, fn_name, arg_count=arg_count if arg_count is not None else len(type_args),
                                 arg_ctypes=arg_ctypes)
        if tmpl is None:
            return None
        params = type_param_names(tmpl)
        targs = bind_type_args(tmpl, type_args)
        if targs is None:
            return None
        # A variadic type-pack param (`*Ts`) collapses to a single bound type
        # (the first arg's) regardless of how many variadic value-args were
        # actually passed (infer_type_args/zip only ever see one slot for it).
        # Two calls with the same element type but different arities (e.g.
        # `chain(a, b)` vs `chain(a, b, c)`) would otherwise mangle/cache to
        # the identical symbol built for whichever arity compiled first,
        # producing a real argument-count mismatch at the other call site.
        # Fold the call arity into the instantiation identity so each arity
        # gets its own mangled symbol/cache entry.
        if arg_count is not None and any(p.startswith('*') for p in params):
            targs['ArgC'] = arg_count
        # Slice 6: a bounded type parameter must conform before we instantiate.
        check_bounds(module_src, tmpl, targs)

        mangled, obj, _hit, cpp_obj = mm.instantiate(tmpl, targs, gcc=self.gcc,
                                                     conformance_bases=_where_conformance_bases(module_src))
        _, concrete = mm.monomorphize_source(tmpl, targs)
        ret, ptypes = _elab_signature(concrete, mangled)
        return {'symbol': mangled, 'object': obj, 'cpp_object': cpp_obj,
                'ret': ret, 'params': ptypes}

    def elaborate_generic_struct(self, module_src: str, struct_name: str,
                                 type_args, nested=None) -> dict:
        """Instantiate a generic struct `Struct[TypeArgs]` (slice 5): monomorphize
        the struct + its methods for the type args (CAS-cached), and report the
        concrete name, field layout, method signatures, and object so the codegen
        can materialize the type, construct it, and call its methods.

        `nested` handles a type argument that is itself a generic-struct mention
        (e.g. `_PeekableIterator[_ListIter[True, Int, ImmOrigin, True]]`): a list
        of `(mention, module_src, struct_name, type_args)`, where `mention` is
        the exact string the caller passed as that nested argument in
        `type_args` and the other three locate the struct's definition. Each
        nested struct is bound-checked and monomorphized here, and its definition
        is spliced into the wrapper's translation unit, so a by-value nested
        field keeps its real layout — the isolated TU resolves the mangled name
        against the definition in the same TU instead of erasing the mention to
        int64_t (see monomorphize.instantiate's splice note for the failure this
        fixes: the wrapper's own `next(self._inner)` refusal)."""
        tmpl = extract_struct_source(module_src, struct_name)
        if tmpl is None:
            return None
        targs = bind_type_args(tmpl, type_args)
        if targs is None:
            return None
        # Slice 6: a bounded type parameter must conform before we instantiate.
        check_bounds(module_src, tmpl, targs)
        _validate_generic_struct_align(module_src, tmpl, struct_name, type_args, targs)

        nested_defs, renames = [], []
        for mention, n_src, n_name, n_args in (nested or []):
            if mention not in type_args:
                return None
            n_tmpl = extract_struct_source(n_src, n_name)
            if n_tmpl is None:
                return None
            n_targs = bind_type_args(n_tmpl, n_args)
            if n_targs is None:
                return None
            check_bounds(n_src, n_tmpl, n_targs)
            n_mangled, n_concrete = mm.monomorphize_source(n_tmpl, n_targs)
            nested_defs.append(n_concrete)
            renames.append((mention, n_mangled))

        mangled, obj, _hit, cpp_obj = mm.instantiate(tmpl, targs, gcc=self.gcc,
                                                     nested_defs=nested_defs,
                                                     renames=renames,
                                                     conformance_bases=_where_conformance_bases(module_src))
        _, concrete = mm.monomorphize_source(tmpl, targs)
        fields, methods, anns = _struct_layout_anns(concrete, mangled)
        # `symbols`: what the TU ACTUALLY defined (`nm`). The caller registers
        # its externs and its `func_return_types` keys from this rather than
        # from a re-derived name, so a declaration and its definition cannot
        # disagree — which is not a hypothetical: an overloaded method is
        # suffixed by a hash of its real C parameter types, and those are not
        # recoverable from the erased view this module has. Empty set on a
        # re-entrant (cycle) instantiation, where no object was built; the
        # caller then falls back to the names it composes itself.
        symbols = sorted(_defined_symbols(obj)) if obj else []
        return {'name': mangled, 'fields': fields, 'methods': methods,
                'anns': anns, 'object': obj, 'cpp_object': cpp_obj,
                'symbols': symbols}

    def elaborate_generic_struct_inferred(self, module_src: str, struct_name: str,
                                          arg_ctypes) -> dict:
        """`Struct(...)` with no bracket arguments: infer the type args from the
        constructor's own parameter annotations (`infer_struct_type_args`), then
        elaborate exactly as the explicit form does."""
        type_args = infer_struct_type_args(module_src, struct_name, arg_ctypes)
        if type_args is None:
            return None
        return self.elaborate_generic_struct(module_src, struct_name, type_args)

    def elaborate_overload_call(self, module_src: str, fn_name: str, arg_ctypes) -> dict:
        """Resolve an overloaded call (slice 4): pick the `fn_name` overload whose
        parameter types match the argument C types, mangle it by signature, and
        compile that one concrete function (CAS-cached). Returns
        {symbol, object, ret, params} or None."""
        overloads = extract_overloads(module_src, fn_name)
        if not overloads:
            return None
        # An argument whose C type has no Mojo spelling (`None`) equals no
        # overload's parameter type, so it matches nothing and declines here.
        arg_mojo = [c_to_mojo(ct) for ct in arg_ctypes]
        chosen = None
        for src, ptypes, ret in overloads:
            if ptypes == arg_mojo:
                chosen = (src, ptypes, ret)
                break
        if chosen is None:
            # No overload matches the argument types — do NOT silently pick the
            # first (review finding #4); let the caller fall through / error.
            return None
        src, ptypes, ret = chosen
        # Sanitize the signature suffix to a valid C identifier (parametric param
        # types like List[Int] contain []/, which are illegal in a C symbol) —
        # INJECTIVELY, via the same length-prefixed encoding `mangle` uses. The
        # previous `safe_suffix('_'.join(ptypes))` was ambiguous segmentation
        # with a lossy escape, so `['A_B']` and `['A', 'B']` named one symbol.
        mangled = mm.mangle_signature(fn_name, ptypes)
        renamed = re.sub(rf'\bfn\s+{re.escape(fn_name)}\b', f'fn {mangled}', src, count=1)
        obj, _hit = mm.compile_fn(renamed, gcc=self.gcc)
        return {'symbol': mangled, 'object': obj,
                'ret': _mojo_type(ret) if ret else 'void',
                'params': [_mojo_type(p) for p in ptypes]}

    def elaborate_generic_call_inferred(self, module_src: str, fn_name: str, arg_ctypes) -> dict:
        """Like elaborate_generic_call but infers the type args from the call
        argument C types (slice 2): `box(42)` with no explicit `[Int64]`."""
        tmpl = extract_fn_source(module_src, fn_name, arg_count=len(arg_ctypes),
                                 arg_ctypes=arg_ctypes)
        if tmpl is None:
            return None
        type_args = infer_type_args(tmpl, arg_ctypes)
        if type_args is None:
            return None
        try:
            return self.elaborate_generic_call(module_src, fn_name, type_args,
                                               arg_count=len(arg_ctypes),
                                               arg_ctypes=arg_ctypes)
        except ConformanceError:
            # A conformance failure inferred from an ERASED argument type is
            # a fact about this codegen's C representation, not about the
            # Mojo source: `tanh(x[i])` on a `Span[Float32]` lowers its
            # argument to `char` (untracked byte element) or `int64_t` (SIMD
            # erasure), `c_to_mojo` reads either as `Int`, and enforcing the
            # `where dtype.is_floating_point()` clause then rejects a valid
            # float call. Six real stdlib files hit exactly that
            # (`std/random/philox.mojo:300`, `test/math/test_{erf,exp,ldexp,
            # math,tanh}.mojo`).
            #
            # A caller that supplies the type args EXPLICITLY (`f[T](...)`)
            # states them, so the diagnostic there is provable and
            # `elaborate_generic_call` still raises it. Here, when ANY
            # argument's C type is a placeholder, decline: the caller falls
            # through to its nominal stub exactly as when no instantiation
            # could be inferred.
            if any(not inferred_ctype_is_specific(ct) for ct in arg_ctypes):
                return None
            raise


def _collect_comptime_aliases(sd):
    aliases = {}
    try:
        for k, v in (getattr(sd, 'comptime_aliases', None) or {}).items():
            aliases[k] = v
        for fld in (getattr(sd, 'fields', None) or []):
            if isinstance(fld, AssignStmt) and isinstance(getattr(fld, 'target', None), IdentExpr):
                aliases.setdefault(fld.target.name, fld.value)
            if isinstance(fld, ComptimeVarStmt):
                name = getattr(fld, 'target', None)
                if isinstance(name, str):
                    aliases.setdefault(name, getattr(fld, 'value', None))
    except Exception:
        pass
    return aliases


def _fn_type_param_bounds(fn):
    bounds = {}
    # comptime_params may be strings or richer; try to parse annotations
    for p in (getattr(fn, 'comptime_params', None) or []):
        if isinstance(p, str):
            bounds[p] = None
        elif isinstance(p, (list, tuple)) and p:
            bounds[p[0]] = p[1] if len(p) > 1 else None
    anns = getattr(fn, 'comptime_param_annotations', None) or {}
    for k, v in anns.items():
        if v:
            bounds[k] = v
    # parse from params-like bracket info not directly stored except comptime_params names
    # also try parsing fn text? not available. Use comptime_param_annotations if present.
    return bounds


def _is_member_type_ref(type_ann):
    # "Box[T].R" or "pkg.Box[T].R" - simple detection
    if not isinstance(type_ann, str):
        return None
    s = type_ann.strip()
    if '.' not in s or '[' not in s:
        return None
    # split last .member
    base_part, _, member = s.rpartition('.')
    if not member or '[' not in base_part:
        return None
    bname, bargs = _split_base_type_args(base_part)
    return (bname, bargs, member, base_part)


def check_signature_binding_evidence(module_src, fn, module_stmts=None):
    """Detect unprovable constrained comptime member uses in signature types."""
    if module_stmts is None:
        try:
            module_stmts = Parser(py_tokenize(module_src)).parse_module()
        except Exception:
            return
    struct_map = {}
    for st in module_stmts:
        if isinstance(st, StructDef):
            struct_map[st.name] = st
    fn_bounds = _fn_type_param_bounds(fn)
    # collect known conforms_to facts from fn bounds: e.g. T: CopyableT
    known = {}
    for p, b in fn_bounds.items():
        if isinstance(b, str) and b:
            known[p] = [x.strip() for x in b.replace('&',',').split(',') if x.strip()]
    # also parse comptime params from function signature text if possible? not needed
    annotations = []
    rt = getattr(fn, 'return_type', None)
    if isinstance(rt, str):
        annotations.append(rt)
    for n, t in (getattr(fn, 'params', None) or []):
        if isinstance(t, str):
            annotations.append(t)
    for ann in annotations:
        ref = _is_member_type_ref(ann)
        if not ref:
            continue
        bname, bargs, member, base_part = ref
        sd = struct_map.get(bname)
        if sd is None:
            continue
        aliases = _collect_comptime_aliases(sd)
        if member not in aliases:
            continue
        val = aliases[member]
        # If alias value is a generic type application like NeedsCopy[T], check its bounds
        try:
            val_text = _expr_constraint_text(val) if not isinstance(val, str) else val
        except Exception:
            val_text = ''
        # parse val_text as Type[Args]
        vb, vargs = _split_base_type_args(val_text)
        if not vargs:
            continue
        target_sd = struct_map.get(vb)
        target_src = extract_struct_source(module_src, vb)
        if target_sd is None or target_src is None:
            continue
        # bind target params to vargs, substituting function's type params
        try:
            tparams = type_param_names(target_src) or []
        except Exception:
            tparams = []
        # Build bindings mapping target params to concrete or fn params
        t_bind = {}
        for i, tp in enumerate(tparams):
            if i < len(vargs):
                t_bind[tp] = vargs[i]
        # Also map struct's own params in bargs context
        sparams = []
        try:
            stmpl = extract_struct_source(module_src, bname)
            sparams = type_param_names(stmpl) if stmpl else []
        except Exception:
            sparams = []
        s_bind = {}
        for i, sp in enumerate(sparams):
            if i < len(bargs):
                s_bind[sp] = bargs[i]
        # resolve vargs through s_bind
        resolved_targs = []
        unproven = False
        for i, tp in enumerate(tparams):
            if i >= len(vargs):
                break
            arg = vargs[i]
            arg_resolved = s_bind.get(arg, arg)
            # check target bound for tp
            try:
                bounds = parse_bounds(target_src)
            except Exception:
                bounds = {}
            bound = bounds.get(tp)
            if not bound:
                resolved_targs.append(arg_resolved)
                continue
            # if arg_resolved is a function type param, see if fn proves it satisfies bound
            if arg_resolved in known:
                k = set(known.get(arg_resolved) or [])
                # simple check: bound name present
                if bound in k:
                    resolved_targs.append(arg_resolved)
                    continue
                # try conforms_to via known bases? limited
            elif arg_resolved not in fn_bounds:
                # concrete type: check conformance directly
                ok, _ = check_conformance(module_src, arg_resolved, bound)
                if ok:
                    resolved_targs.append(arg_resolved)
                    continue
            # unproven
            unproven = True
            break
        if unproven:
            raise RuntimeError(
                "error: invalid bindings in signature: lacking evidence to prove correctness\n"
                "note: add a trailing 'where' clause to the function declaration"
            )



def _fn_known_bounds(fn, module_src, module_stmts):
    known = {}
    # from comptime_param_annotations
    for k, v in (getattr(fn, 'comptime_param_annotations', None) or {}).items():
        if isinstance(v, str) and v:
            known.setdefault(k, set()).update(x.strip() for x in v.replace('&',',').split(',') if x.strip())
    # try to parse comptime params text from source? not easy. also check comptime_params elements
    for p in (getattr(fn, 'comptime_params', None) or []):
        if isinstance(p, (list, tuple)) and len(p) >= 2 and isinstance(p[1], str):
            known.setdefault(p[0], set()).update(x.strip() for x in p[1].replace('&',',').split(',') if x.strip())
    # fallback: parse from function signature line in module_src
    try:
        # find "def fnname[" in module_src
        name = getattr(fn, 'name', '')
        if name:
            # simple regex
            m = re.search(rf'\bdef\s+{re.escape(name)}\s*\[([^\]]*)\]', module_src)
            if m:
                inner = m.group(1)
                # split params
                for part in gimple_exprtypes_split_commas(inner):
                    part = part.strip()
                    if ':' in part:
                        pn, pb = part.split(':', 1)
                        pn = pn.strip().lstrip('*')
                        pb = pb.strip()
                        if pn and pb:
                            known.setdefault(pn, set()).update(x.strip() for x in pb.replace('&',',').split(',') if x.strip())
    except Exception:
        pass
    return known


def gimple_exprtypes_split_commas(s):
    # local fallback
    out, depth, cur = [], 0, []
    for c in s:
        if c in '([{': depth += 1
        elif c in ')]}': depth -= 1
        if c == ',' and depth == 0:
            out.append(''.join(cur)); cur=[]
        else:
            cur.append(c)
    if cur: out.append(''.join(cur))
    return out


def _walk_nodes(node):
    if node is None:
        return
    if isinstance(node, list):
        for x in node:
            yield from _walk_nodes(x)
        return
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk_nodes(v)
        return
    try:
        fields = getattr(node, '__dataclass_fields__', None)
        if fields:
            for f in fields:
                yield from _walk_nodes(getattr(node, f))
            return
    except Exception:
        pass
    # fallback common attrs
    for attr in ('body','then_body','else_body','elifs','value','args','kwargs','func','obj','target','iterable','condition','left','right','operand','elements'):
        if hasattr(node, attr):
            try:
                yield from _walk_nodes(getattr(node, attr))
            except Exception:
                pass


def check_method_call_evidence(module_src, fn, module_stmts=None):
    if module_stmts is None:
        try:
            module_stmts = Parser(py_tokenize(module_src)).parse_module()
        except Exception:
            return
    struct_map = {}
    for st in module_stmts:
        if isinstance(st, StructDef):
            struct_map[st.name] = st
    # param name -> type annotation string
    param_types = {}
    for n, t in (getattr(fn, 'params', None) or []):
        if isinstance(n, str) and isinstance(t, str):
            param_types[n] = t
    known_bounds = _fn_known_bounds(fn, module_src, module_stmts)
    # build a conforms_to predicate based on known bounds (conservative)
    bases = _where_conformance_bases(module_src)
    def _known_conforms(t, tr):
        # t may be a fn type param name
        if t in known_bounds:
            ks = known_bounds[t]
            if tr in ks:
                return True
            # ancestor check via bases: if t known to conform to X and X conforms to tr
            for k in list(ks):
                try:
                    if conforms_to(k, tr, bases) is True:
                        return True
                except Exception:
                    pass
        # concrete type
        try:
            if conforms_to(t, tr, bases) is True:
                return True
        except Exception:
            pass
        return None

    for node in _walk_nodes(getattr(fn, 'body', None)):
        if not isinstance(node, CallExpr):
            continue
        func = getattr(node, 'func', None)
        if not isinstance(func, MemberExpr):
            continue
        obj = getattr(func, 'obj', None)
        if not isinstance(obj, IdentExpr):
            continue
        recv_type = param_types.get(obj.name)
        if not recv_type:
            continue
        rb, rargs = _split_base_type_args(recv_type)
        sd = struct_map.get(rb)
        if sd is None:
            continue
        method_name = func.member
        # find method in struct
        mdef = None
        for m in (getattr(sd, 'methods', None) or []):
            if getattr(m, 'name', None) == method_name:
                mdef = m
                break
        if mdef is None:
            continue
        mw = getattr(mdef, 'where_clause', None)
        if mw is None:
            continue
        mw_text = _expr_constraint_text(mw) if not isinstance(mw, str) else mw
        # substitute struct type params with rargs
        bindings = {}
        try:
            stmpl = extract_struct_source(module_src, rb)
            sparams = type_param_names(stmpl) if stmpl else []
            for i, sp in enumerate(sparams):
                if i < len(rargs):
                    bindings[sp] = rargs[i]
                    bindings[f'Self.{sp}'] = rargs[i]
        except Exception:
            pass
        mw_text = _substitute_constraint_text(mw_text, bindings)
        try:
            st = eval_const_bool_state(Parser(py_tokenize(mw_text))._parse_expr(0), {}, conforms_to_pred=_known_conforms)
        except Exception:
            st = None
        if st == CONST_FALSE or st is None or st == -1:
            # If provably false or undecidable given known bounds in generic context -> lacking evidence
            # "do not report on unknown evidence" in general, but for this specific call in generic
            # context with insufficient bounds we must report lacking evidence per case 4/5.
            if st == CONST_TRUE:
                continue
            raise RuntimeError("lacking evidence to prove correctness")

