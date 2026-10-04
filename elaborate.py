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
import re
import subprocess

import monomorphize as mm
from fire_compiler import (py_tokenize, Parser, FunctionDef, StructDef,
                          TraitDef, split_top_level_commas)
from gimple_codegen import _mojo_type


class ConformanceError(Exception):
    """A concrete type does not satisfy a generic's trait bound (slice 6).

    Raised when elaborating `f[T]`/`Struct[T]` whose type parameter carries a
    trait bound that the concrete type does not meet (it is missing a required
    method, or its signature differs). The message is the compile error a user
    sees."""

# The generic head is `monomorphize.head_match`, which finds it with BRACKETS
# BALANCED rather than with a `[^\]]*` class -- a parameter whose type is itself
# a type application (`keys: List[T]`, `width: SIMD[dtype, width]`) puts a `]`
# inside the parameter list, and every reader below wants the whole list. This
# file used to carry its own two copies of that regex; one reader of one rule is
# the point (`bugs/MONOMORPH_a_bracket_in_a_template_parameter_annotation_is_not_matched.md`).


def _bracket_depth_by_line(module_src: str) -> list[int]:
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
    the extracted template before its real body."""
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
    return depths


def _find_block_end(lines: list[str], depths: list[int], start: int, base: int) -> int:
    """First line index after `start` that both dedents to <= `base`
    indentation AND sits at bracket depth 0 — i.e. an ordinary top-level
    statement boundary, not a continuation of a still-open `([{` header."""
    for j in range(start + 1, len(lines)):
        l = lines[j]
        d = depths[j] if j < len(depths) else 0
        if l.strip() and d == 0 and (len(l) - len(l.lstrip())) <= base:
            return j
    return len(lines)


def extract_fn_source(module_src: str, fn_name: str, arg_count: int | None = None):
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
    for src in candidates:
        for s in Parser(py_tokenize(src)).parse_module():
            if isinstance(s, FunctionDef) and s.name == fn_name:
                n = len([1 for pn, _ in s.params if pn != 'self' and not pn.startswith('*')])
                if n == arg_count:
                    return src
                break
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
    bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md).
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
    `bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md`.

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
    ones before it."""
    params = type_param_names(template_src)
    if not params:
        return None
    supplied = list(type_args or ())
    if len(supplied) > len(params):
        supplied = supplied[:len(params)]
    defaults = type_param_defaults(template_src) if len(supplied) < len(params) else {}
    targs = {}
    for i, p in enumerate(params):
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


def type_methods(module_src: str, type_name: str):
    """The method signatures a concrete `struct type_name` defines, as a list
    of (name, [param_types], ret_type). None if the type is not a struct here."""
    for s in Parser(py_tokenize(module_src)).parse_module():
        if isinstance(s, StructDef) and s.name == type_name:
            return [_method_sig(m) for m in s.methods]
    return None


def check_conformance(module_src: str, type_name: str, trait_name: str):
    """Does concrete `type_name` satisfy `trait_name`? Returns (ok, missing),
    where `missing` lists human-readable descriptions of unmet requirements.

    A requirement is met when the type defines a method of the same name whose
    (param types, return type) match. If the trait is unknown we cannot check
    it, so we conservatively accept (ok=True) — bounds we don't understand do
    not block instantiation, matching the demand-driven, best-effort style."""
    required = extract_trait(module_src, trait_name)
    if required is None:
        return True, []
    have = type_methods(module_src, type_name)
    if have is None:
        # No struct source to inspect (e.g. a builtin like Int). We cannot
        # verify, so we do not block — keep behaviour additive.
        return True, []
    by_name = {}
    for name, ptypes, ret in have:
        by_name.setdefault(name, []).append((ptypes, ret))
    missing = []
    for name, ptypes, ret in required:
        cands = by_name.get(name)
        if cands is None:
            missing.append(f"missing method '{name}'")
            continue
        if not any(cp == ptypes and cr == ret for cp, cr in cands):
            want = f"({', '.join(ptypes)}) -> {ret}"
            missing.append(f"method '{name}' signature mismatch (want {want})")
    return (not missing), missing


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


def c_to_mojo(ctype: str) -> str:
    return _C_TO_MOJO.get(ctype, 'Int')


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

    `width` binds to `1`, which is not a guess about the source: this codegen
    erases SIMD outright (`_mojo_type('SIMD[Float64, 4]')` is `int64_t`, and
    `_TYPE_MAP` has no SIMD key), so every value that reaches here is a scalar,
    and `SIMD[<scalar type>, 1]` is the spelling that means "that scalar". A
    future real SIMD representation must revisit this one line.

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
        return {ann: c_to_mojo(arg_ctype)}
    m = _SIMD_ANN_RE.match(ann)
    if m and m.group(1) in pnames:
        out = {m.group(1): c_to_mojo(arg_ctype)}
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
    if any(p not in binding for p in params):
        return None
    return [binding[p] for p in params]


def infer_struct_type_args(module_src: str, struct_name: str, arg_ctypes):
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
    `bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md`).

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
    for ctor in ctors:
        anns = [ann for pn, ann in ctor.params
                if pn != 'self' and not pn.startswith('*')]
        if len(anns) != len(arg_ctypes):
            continue
        binding = {}
        for ann, ct in zip(anns, arg_ctypes):
            for k, v in _unify_param_ann(ann, params, ct).items():
                binding.setdefault(k, v)
        binding = _fill_erased_params(tmpl, params, binding)
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
            fields.append((f.name, _mojo_type(f.type_ann)))
            anns.append((f.name, 'field', 0, f.type_ann))
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
            return ret, [_mojo_type(t) for _, t in s.params]
    return 'int64_t', []


def _defined_symbols(obj: str) -> set:
    """External symbols DEFINED (not undefined) by an object file, via `nm`.

    This is how the elaborator learns what the instantiation TU actually NAMED
    its methods, instead of re-deriving the names — which is impossible, and
    was measured impossible (see the `FormatStruct` section of
    bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md:
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


class Elaborator:
    """Demand-driven, CAS-backed elaboration service."""

    def __init__(self, gcc=None):
        self.gcc = gcc

    def elaborate_generic_call(self, module_src: str, fn_name: str, type_args, arg_count: int | None = None):
        """Instantiate `fn_name` for `type_args` (a list of concrete type strings)
        via the CAS. Returns a dict {symbol, object, ret, params} or None.

        `arg_count` (the call's actual argument count, when known) disambiguates
        same-named generic overloads distinguished only by arity (e.g.
        itertools.product's 2/3/4-iterable versions) — see extract_fn_source.

        Elaborate-once-ever: the instantiation is content-addressed, so a repeat
        (here or in another program) is a cache hit."""
        tmpl = extract_fn_source(module_src, fn_name, arg_count=arg_count if arg_count is not None else len(type_args))
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

        mangled, obj, _hit, cpp_obj = mm.instantiate(tmpl, targs, gcc=self.gcc)
        _, concrete = mm.monomorphize_source(tmpl, targs)
        ret, ptypes = _elab_signature(concrete, mangled)
        return {'symbol': mangled, 'object': obj, 'cpp_object': cpp_obj,
                'ret': ret, 'params': ptypes}

    def elaborate_generic_struct(self, module_src: str, struct_name: str, type_args):
        """Instantiate a generic struct `Struct[TypeArgs]` (slice 5): monomorphize
        the struct + its methods for the type args (CAS-cached), and report the
        concrete name, field layout, method signatures, and object so the codegen
        can materialize the type, construct it, and call its methods."""
        tmpl = extract_struct_source(module_src, struct_name)
        if tmpl is None:
            return None
        targs = bind_type_args(tmpl, type_args)
        if targs is None:
            return None
        # Slice 6: a bounded type parameter must conform before we instantiate.
        check_bounds(module_src, tmpl, targs)

        mangled, obj, _hit, cpp_obj = mm.instantiate(tmpl, targs, gcc=self.gcc)
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
                                          arg_ctypes):
        """`Struct(...)` with no bracket arguments: infer the type args from the
        constructor's own parameter annotations (`infer_struct_type_args`), then
        elaborate exactly as the explicit form does."""
        type_args = infer_struct_type_args(module_src, struct_name, arg_ctypes)
        if type_args is None:
            return None
        return self.elaborate_generic_struct(module_src, struct_name, type_args)

    def elaborate_overload_call(self, module_src: str, fn_name: str, arg_ctypes):
        """Resolve an overloaded call (slice 4): pick the `fn_name` overload whose
        parameter types match the argument C types, mangle it by signature, and
        compile that one concrete function (CAS-cached). Returns
        {symbol, object, ret, params} or None."""
        overloads = extract_overloads(module_src, fn_name)
        if not overloads:
            return None
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

    def elaborate_generic_call_inferred(self, module_src: str, fn_name: str, arg_ctypes):
        """Like elaborate_generic_call but infers the type args from the call
        argument C types (slice 2): `box(42)` with no explicit `[Int64]`."""
        tmpl = extract_fn_source(module_src, fn_name, arg_count=len(arg_ctypes))
        if tmpl is None:
            return None
        type_args = infer_type_args(tmpl, arg_ctypes)
        if type_args is None:
            return None
        return self.elaborate_generic_call(module_src, fn_name, type_args, arg_count=len(arg_ctypes))
