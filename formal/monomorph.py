#!/usr/bin/env python3
"""formal/monomorph.py — specialization discovery and instantiation for the
formal dylib path.  This is `doc/ABI.md` §Generics' "Stage 5", and it is the
whole of what that section names:

    A generic is not a single symbol; each instantiation is.  The boundary
    symbol for `Generic[Args]` is the monomorphized function, mangled as
    `Generic__method__<mangled-type-args>`, keyed in the CAS by `hash(template-id,
    concrete type args, comptime params)`.

Until now the compiled path monomorphized generics inline in its codegen and
this path did not monomorphize at all, so a module that declared only a generic
struct template (`std/collections/binary_heap.mojo`'s `BinaryHeap[T]`,
`std/stat/stat.mojo`'s seven `S_ISxxx[intable: Intable]`) had no boundary symbol
of any kind and was refused by the dylib export gate with
`formal/build.py::no_public_api_reason`'s "a parametric type has no single
boundary layout either".  That refusal is correct about the file and it is also
the second wall behind the 165-file row in
`bugs/FORMAL_sweep_work_map_2026-10-03_b8.md` §4.1: past every codegen refusal
in `binary_heap.mojo`, the module-dylib build still failed there.

THE SHAPE OF THE ANSWER, and why it is a generated source file rather than a
new emitter path:

  * `demands(consumer, module_src)` — which instantiations of `module_src`'s own
    templates a consumer source asks for.  Demand-driven, so a module publishes
    the instantiations someone actually imports rather than a guessed universe.
  * `instantiate_all(module_src, demands)` — the CONCRETE source of each one,
    one mangled definition per instantiation, textually substituted by the one
    `monomorphize.py` already owns.
  * The caller compiles those concrete sources into the DEFINING module's own
    dylib, with that module's ABI prefix.  Everything downstream — the export
    table (`reflect.collect_exports_src`), `no_public_api_reason`'s gate, the
    method-symbol naming (`model.abi_method_symbol`), `_method_exports`, and the
    emitters — then sees ordinary concrete declarations and needs to know nothing
    about generics.  That is the point: a new emitter path would have had to
    agree with all five of those, and a generated definition cannot disagree with
    them because it goes through them.

WHAT IS REUSED, and why that is load-bearing rather than tidiness.  Per
CLAUDE.md the compiled path's monomorphizer is not to be reimplemented:

  * `reflect.export_exclusions`'s `EXCL_GENERIC` decides which declared names
    are templates.  `collect_exports_src` filters the export table through the
    SAME function, so the set this module instantiates and the set the gate
    excludes are one decision read twice, not two implementations.
  * `elaborate.extract_struct_source` / `extract_fn_source` /
    `type_param_names` pull one template's text out of a module, with the
    bracket-aware block-end rule (`_bracket_depth_by_line`) that a generic's
    multi-line header needs.
  * `monomorphize.mangle`, `safe_suffix` and `monomorphize_source` are THE
    mangling and THE instantiation.  A second mangling would be a second ABI
    spelling for one concept, and its failure mode is precisely the one
    `doc/ABI.md` §Generics exists to prevent: two instantiations, one trie
    entry, and a call that silently binds the wrong body.

All three are imported LAZILY, inside the functions that use them, and the reason
is `_export_entries`'s own note: each of them reaches `gimple_codegen`, which
drags the whole compiled backend in with it, and a formal build must not pay for
that on a path that does not need it.  On the dylib path it is already loaded
(`_export_entries` calls `import reflect` for exactly the export decision), so
this costs a dict lookup rather than a module.

WHAT IS REFUSED, and it is the safety property of the whole thing.  A type
argument must be a CONCRETE spelling — an identifier, a dotted name, or a nested
type application.  Anything computed is refused rather than mangled, because the
mangled name is the ABI: `Pair[t](0)` is not `Pair_Int` and publishing a symbol
under that name would bind every such call to whichever instantiation happened to
be built first.  A comptime specialization of a template defined in ANOTHER
module (`tile[2, 3](…)`) is likewise not a demand here — its bracket items are
values rather than types, and the local-specialization machinery
(`mojo/middle/comptime.specialization_args` on both backends) already owns the
answer for a template this unit compiles.  `bugs/FORMAL_generic_monomorph_scope.md`
records what that leaves.
"""

import hashlib
import re

import fire_compiler as F


class MonomorphError(Exception):
    """A demand this module cannot satisfy, with the reason in one sentence."""


KIND_STRUCT = "struct"
KIND_FN = "def"

# ── derivations of a SOURCE, made once per distinct source ───────────────
#
# Two questions in this module are pure functions of a source TEXT and are each
# asked once per module of the consumer's import CLOSURE rather than once per
# source: `template_names` (below, via `formal/imports.py::
# module_templates_by_path`, which walks every module a module re-exports and
# asks each one which of its declared names are templates) and
# `all_instantiation_calls` (via `formal/imports.py::instantiation_demands`,
# once per imported module, for a consumer whose text is the same every time).
# Both derivations start by tokenizing and parsing the text, and both were
# paying for that once per walk rather than once per source.
#
# MEASURED, on `std/simd.mojo` (4 462 lines, 20 import statements, 84.3 s):
# `fire_compiler.py_tokenize` ran 7 335 times, 7 042 of them from
# `template_names` — one per (closure walk x module), the walk repeated once per
# imported module by `instantiation_demands` and again by
# `formal/build.py::_resolve_imports`. `cProfile` put 100.6 s of a 197.5 s
# instrumented build inside `py_tokenize_named`, i.e. 51% of the whole build, and
# `formal/model.py`'s walks — the thing the 2026-10-02 build-cost pass spent its
# budget on — came to 1.8 s of the 84 s. On `myinterpreter.py` the same shape is
# 7 re-parses of one 271 KB source, 0.68 s of a 2.7 s build.
#
# So this is not a cache of something that CHANGES: both answers are functions of
# the source text alone, and the text is the key. A build that edits a module's
# source reads a different key, which is why nothing here needs an invalidation
# argument (the same argument `formal/imports.py::module_statements` makes for its
# own content-keyed parse cache, and the one that doc's §3.1 makes about
# threading a table instead).
#
# KEYED BY A DIGEST, not by the text, and that is a memory decision rather than a
# speed one: holding the sources as keys would retain every module text of every
# build this process ever did, where `formal/imports.py::_SOURCE_TEXT` already
# holds them for the build in flight. blake2b over the source is 0.16 ms on a
# 200 KB module against the 13 ms parse it stands in for, and 16 bytes against
# 200 KB of retained key. A 128-bit digest is not a probabilistic answer to
# "which source is this" — two sources colliding on it would have to be found by
# an adversary, and the alternative that does not collide (the text itself) is
# the retention above.
#
# BOUNDED, FIFO, because this process is the sweep's: one file per build and one
# process per file today, but a bound is what keeps a long-lived one from growing
# without limit. The cap is far above one build's working set (~160 modules for
# `std/simd.mojo`'s closure), so a build never evicts what it is about to ask
# again, and an eviction is a re-derivation and never a wrong answer.
#
# KEYED BY THE QUESTION AS WELL AS THE SOURCE, which is not tidiness: the first
# version of this keyed on the digest alone, and a module that is asked BOTH
# questions about ITSELF — `template_names` and `all_instantiation_calls` share
# `module_source_text(path)` at `formal/imports.py::build_module_dylib` — then
# read one question's answer out of the other's slot. Measured as a crash on 4 of
# the 43 files of the byte-comparison spread
# (`'tuple' object has no attribute 'items'`, the cached template-name tuple read
# as a demand set), which is the whole reason the key carries `tag`.
_DERIVED: dict = {}
_DERIVED_CAP = 4096


def _derived_from_source(tag: str, src: str, compute, subkey=None):
    """`compute()` for `(tag, src, subkey)`, once per distinct triple.

    `compute` is called with no arguments and must be a function of `src` and
    `subkey` and nothing else — no module path, no parse tree, no mutable state
    of this process — because the cache is keyed on those ALONE.  Everything
    stored here is derived that way; the docstring above names the callers and
    each of their derivations is a `reflect`/`elaborate` question about source
    text.  `tag` names the QUESTION, so two questions about one source cannot
    read each other's answers, and `subkey` carries the two callers that ask a
    per-name question about a source (`template_kind` and `_template_source`,
    which `instantiate` asks in a row).
    """
    key = (tag, subkey,
           hashlib.blake2b(src.encode("utf-8", "surrogatepass"),
                           digest_size=16).digest())
    hit = _DERIVED.get(key)
    if hit is not None:
        return hit
    val = compute()
    if len(_DERIVED) >= _DERIVED_CAP:
        del _DERIVED[next(iter(_DERIVED))]      # FIFO: the oldest insertion
    _DERIVED[key] = val
    return val


# ── which declared names are templates ───────────────────────────────────


def template_names(src: str) -> list:
    """The GENERIC TEMPLATE names `src` declares, in declaration order.

    Read out of `reflect.export_exclusions`, which is the ONE place
    `doc/ABI.md`'s public-symbol rule is stated and the function
    `reflect.collect_exports_src` filters the export table through.  So the
    names this module instantiates are exactly the names the export rule
    excluded as `EXCL_GENERIC`, and a change to the rule moves both together.

    Not a second regex over the source: `_excluded_name_sets`'s own docstring
    records the one known imprecision of the rule it reads (a NESTED
    `def name[...]` puts the name in the template set), and duplicating the
    rule here would fork that imprecision into a second place to be wrong about.

    **Once per source text, not once per module of a closure.**  The question is
    a function of `src` alone, and `formal/imports.py::module_templates_by_path`
    asks it of every module in a re-export closure, once per imported module of
    the consumer — 7 042 tokenizations on `std/simd.mojo` where there are 160
    modules to ask about.  The measurement and the key are in the module-level
    note above `_DERIVED`; the answer is returned as a fresh `list` on every call
    so that a caller mutating what it got back cannot reach into the cached one.
    """
    import reflect                                  # lazy — see the module docstring
    return list(_derived_from_source("template_names", src, lambda: tuple(sorted(
        name for name, why in reflect.export_exclusions(src).items()
        if why == reflect.EXCL_GENERIC))))


def template_kind(src: str, name: str) -> str:
    """`KIND_STRUCT` if `name` is a generic struct template in `src`, else
    `KIND_FN`; raise `MonomorphError` when `src` declares neither.

    Asked of the SOURCE rather than answered from `templates_in`'s caller
    because the two extractors are what actually find the template, and a name
    the export rule filed as a template that neither extractor can pull out is
    the nested-`def` imprecision above rather than a template — which is a fact
    the caller needs told rather than an instantiation it needs built.

    **Once per `(source, name)`, because the extractors are whole-module
    scans.**  `elaborate.extract_struct_source` and `extract_fn_source` each
    `splitlines()` the module and run `elaborate._bracket_depth_by_line` over
    it, and `instantiate` asks this question once per (template, argument-list)
    pair — 300 times on `std/simd.mojo`, over FOUR distinct `(source, name)`
    pairs, for 600 bracket-depth scans of whole modules and 8.4 s of a 21.6 s
    instrumented build.  So the answer goes through `_derived_from_source` with
    the name as its subkey, and a refusal is NOT stored: `_derived_from_source`
    only caches a value that is not None, so a name no extractor finds is
    re-derived (and re-refused) every time, which is what happened before.
    """
    return _derived_from_source("template_kind", src,
                                lambda: _kind_of(src, name), subkey=name)


def _kind_of(src: str, name: str) -> str:
    """The `KIND_*` for `name` in `src`, or raise. The body of `template_kind`.

    Split out so the memo in `template_kind` wraps ONE call and the refusal
    stays a `raise` in the ordinary place rather than a sentinel a caller has
    to know about.
    """
    import elaborate                                # lazy — see the module docstring
    if elaborate.extract_struct_source(src, name) is not None:
        return KIND_STRUCT
    if elaborate.extract_fn_source(src, name) is not None:
        return KIND_FN
    raise MonomorphError(
        f"{name!r} is excluded from the export set as a generic template but "
        f"neither a `struct {name}[…]` nor a `def {name}[…]` can be read out "
        f"of this module — the rule that filed it matches a nested "
        f"`def {name}[…]` inside a function body as readily as a top-level "
        f"template, and only a top-level one is instantiable")


def _template_source(src: str, name: str, kind: str) -> str:
    """`name`'s own declaration text, read out of `src`.

    The SECOND reader of the extractors `template_kind` above just used, for
    the same source and the same name, so it is memoized the same way and on
    the same key's subkey: `instantiate` asks both questions in a row and each
    ask was a pair of whole-module bracket-depth scans.  A template that is
    not in the source is not stored either — see `template_kind`'s note — so
    the refusal below still fires rather than being served from the cache.
    """
    import elaborate
    got = _derived_from_source(
        "_template_source", src,
        lambda: (elaborate.extract_struct_source(src, name)
                 if kind == KIND_STRUCT
                 else elaborate.extract_fn_source(src, name)),
        subkey=(name, kind))
    if got is None:
        raise MonomorphError(f"no {kind} template {name!r} in this module")
    return got


# ── the instantiation itself ───────────────────────────────────────────


def _fold_self_params(template_src: str, params) -> str:
    """`Self.T` → `T` for each type parameter, in the template's own text.

    Inside a struct template `Self.T` and `T` name the same parameter — that is
    what `std/collections/binary_heap.mojo`'s `var _data: List[Self.T]` and
    `List[Self.T]()` mean.  The shared substitution in `monomorphize_source` is
    a whole-word `re.sub` of each parameter's spelling, and `\bT\b` matches the
    `T` in `Self.T` just as happily as the bare one, so without this fold it
    produces `List[Self.Int]` — a spelling nothing declares and nothing binds.
    Done here rather than by editing `monomorphize_source` because that
    substitution is the COMPILED path's, its callers hand it templates in which
    `Self.T` cannot appear (the gimple path never parses a struct template as a
    unit), and teaching it about `Self` would be a change to a shared engine on
    the strength of a caller that does not exist on that path.

    Takes the parameter NAMES rather than deriving them: the caller has already
    asked the template for them (to check the bracket's arity), and asking twice
    would be two reads of one declaration that could disagree.
    """
    out = template_src
    for p in params:
        out = re.sub(rf"\bSelf\s*\.\s*{re.escape(p)}\b", p, out)
    return out


def instantiate(src: str, name: str, args) -> tuple:
    """`(mangled_name, concrete_source)` for `name[args]` inside `src`.

    `args` is the consumer's own spelling of the type arguments, in bracket
    order, and it is checked against the template's DECLARED parameter count
    before anything is substituted: a bracket with the wrong arity is not an
    instantiation of this template, and mangling it anyway would publish a
    symbol whose body was built from a parameter the source never bound.
    """
    import elaborate, monomorphize                 # lazy — module docstring
    kind = template_kind(src, name)
    template_src = _template_source(src, name, kind)
    params = elaborate.type_param_names(template_src)
    if not params:
        raise MonomorphError(
            f"{name!r} is excluded from the export set as a generic template "
            f"but its declaration has no type parameter, so there is nothing to "
            f"substitute and no instantiation is a different function")
    args = [str(a) for a in args]
    if len(args) != len(params):
        raise MonomorphError(
            f"{name}[{', '.join(args)}] supplies {len(args)} type "
            f"argument{'s' if len(args) != 1 else ''} but `{name}` declares "
            f"{len(params)} ({', '.join(params)}); an instantiation is one "
            f"template specialized for exactly the arguments it declares")
    targs = dict(zip(params, args))
    try:
        mangled, concrete = monomorphize.monomorphize_source(
            _fold_self_params(template_src, params), targs)
    except ValueError as e:
        # `monomorphize_source` raises `ValueError` for a type parameter that is
        # ALSO a binding name in the body (`var T = …`, `for T in …`,
        # `T = …`): a whole-word textual substitution would rewrite the value
        # identifier to a type name, and it refuses rather than miscompile.  The
        # refusal is right and it is not this module's error to raise — a
        # template like that has a legal spelling nobody on this path
        # instantiates yet, so the demand is dropped and the call site keeps its
        # brackets and is refused by the bracketed scan, which is the sentence
        # that is true of it.  Leaving it to propagate is what a measurement
        # caught: `std/python/bindings.mojo` (the largest file in the sweep,
        # and the one `test_formal_imports.py`'s bounded-build case exists for)
        # died with this `ValueError` out of `monomorphize_source` instead of
        # being CLASSIFIED, so the sweep recorded a backend crash rather than a
        # construct refusal.
        raise MonomorphError(str(e)) from None
    return mangled, concrete


# ── which instantiations a consumer asks for ───────────────────────────


def type_arg_text(expr, values=()) -> str:
    """The ABI spelling of a type ARGUMENT, or "" when it is not one.

    "" is the answer for everything that is not a type spelling, and it is a
    refusal rather than a fallback: a computed argument has no single name, and
    inventing one is how a call binds another instantiation's body (the reason
    `no_public_api_reason` refuses to export a template under its base name).
    The accepted shapes are the three a type argument is written in:

        `Int`            an identifier
        `simd.float32`   a dotted name
        `List[Int]`      a type application, spelled `List_Int` so the mangled
                         name is a legal symbol fragment through the ONE
                         mangler (`monomorphize.safe_suffix`) rather than a
                         second copy of that rule here

    **A BARE IDENTIFIER must not be a name the reading scope BINDS AS A VALUE,
    and this is the sharp edge of the whole module, so it is worth being exact
    about what goes wrong without it.**  `Pair2[t]()` with `var t = Float64`
    reads as `Pair2[t]` — an identifier, a spelling, a demand — and the
    instantiation substituted `T` → `t`, so the library compiled
    `struct Pair2_t: var first: t` with `t` undeclared in the module that owns
    the file.  Nothing in that build objects: a field's declared type is not
    read by `struct_is_framed` (which counts fields, not types), so `Pair2_t`
    framed as two words and `first + second` compiled as the integer addition
    the machine can do.  Measured, and it is the exact failure
    `no_public_api_reason`'s docstring says must not happen — "a build-error
    traded for a run-time wrong answer":

        var t = Float64 ; a = Pair2[t]() ; a.first = 1.5 ; a.second = 2.5
        print(a.scaled())      # CPython 4.0, this path 3

    So `values` is the reading scope's own bindings —
    `formal/build.py::_names_bound_in` for a function (parameters, assignments,
    loop targets; the same union the register allocator is checked against) and
    `formal/model.py::collect_module_symbols` for the module level — and a bare
    identifier in that set is a VALUE, not a type.

    **The check is deliberately the NEGATION and not a list of type names.**
    `formal/model.py::is_type_name` is the existing "spells a TYPE on this
    path" predicate and it is the wrong one to ask: its own docstring says it
    must never be used to answer "can this name be read", and it is INCOMPLETE
    for this purpose by construction — `Float64` and `Float32` are in none of
    its four tables (`POINTEE_WIDTHS` has `Int` and no float), so asking it
    would refuse `Pair2[Float64]()`, which is correct Mojo.  A name that nothing
    binds is a type; a name something binds is a value unless a type is
    declared with that spelling, and the second half of that sentence is the
    documented limit (`bugs/FORMAL_generic_monomorph_scope.md`): a type
    declared in the CONSUMER's own file is refused rather than instantiated.

    `F.IntLiteral` and every expression form are refused, which is also what
    keeps `tile[2, 3](…)` — a comptime specialization whose bracket items are
    VALUES — from being read as a demand for `tile_2_3`.
    """
    if isinstance(expr, F.IdentExpr):
        return "" if expr.name in (values or ()) else (expr.name or "")
    if isinstance(expr, F.MemberExpr):
        obj = type_arg_text(expr.obj, values)
        return f"{obj}.{expr.member}" if obj and expr.member else ""
    if isinstance(expr, F.SubscriptExpr):
        obj = type_arg_text(expr.obj, values)
        inner = type_arg_text(expr.index, values)
        if not obj or not inner:
            return ""
        import monomorphize                         # lazy — module docstring
        return f"{obj}_{monomorphize.safe_suffix(inner)}"
    return ""


def all_instantiation_calls(consumer_src: str) -> dict:
    """`{base name: sorted([(type arg, …), …])}` — every bracketed callee in
    `consumer_src` whose bracket spells concrete TYPE arguments.

    Unfiltered: it does not know which module declares what, because that is a
    question about the import closure and this is a question about ONE source.
    A program importing `std.collections` reaches thirty modules through its
    package's re-exports (`formal/imports.py::instantiation_demands`), so
    filtering per module by re-parsing the consumer made the cost of a demand
    set a product where it only needed to be a sum.

    The walk is per top-level statement rather than one flat walk, because
    "is this identifier a value binding" is a question about the SCOPE the call
    is written in and `iter_nodes` has no parent: `Pair[t]()` is a demand when
    `t` is a type and not one when `t` is the local `var t = Float64` two lines
    above it, and nothing below the callee can tell those apart. So each
    function is walked with its own bindings
    (`formal/build.py::_names_bound_in`) and each module-level statement with
    the module's own table (`formal/model.py::collect_module_symbols`).

    **Once per source text, not once per imported module.**  The paragraph above
    removed the re-parse PER MODULE FILTER and left the parse itself once per
    call, and the call is still made once per imported module
    (`formal/imports.py::instantiation_demands`) over one unchanged consumer —
    7 extra full parses of a 271 KB `myinterpreter.py` and 22 each of
    `std/simd.mojo`, measured.  The answer is a function of the text alone, so
    it is derived once per distinct text (`_derived_from_source`, whose key and
    bound are documented above `_DERIVED`) and handed back as a fresh dict of
    fresh lists on every call.
    """
    def derive():
        from formal import model as M                  # lazy — cycle
        from formal.build import _names_bound_in       # lazy — cycle
        stmts = _consumer_statements(consumer_src)
        module_level = set(M.collect_module_symbols(stmts) or {})
        found: dict = {}
        for st in stmts:
            values = _names_bound_in(st) \
                if isinstance(st, F.FunctionDef) else module_level
            for node in M.iter_nodes(st):
                if not isinstance(node, F.CallExpr):
                    continue
                base = _callee_base(node)
                if base is None:
                    continue
                args = _bracket_type_args(node.func, values)
                if args:
                    found.setdefault(base, set()).add(tuple(args))
        return {k: tuple(sorted(v)) for k, v in found.items()}
    return {k: list(v) for k, v in _derived_from_source(
        "all_instantiation_calls", consumer_src, derive).items()}


def demands_from_calls(found: dict, templates, own=()) -> dict:
    """`found` restricted to `templates`, minus the consumer's own `own`.

    `found` comes from `all_instantiation_calls` over the same source, so the two
    halves of one consumer cannot disagree about what it wrote.
    """
    wanted = {n for n in (templates or ()) if n} - {n for n in (own or ()) if n}
    return {n: [a for a in found.get(n, ())] for n in sorted(wanted)
            if found.get(n)}


def demands(consumer_src: str, templates, own=()) -> dict:
    """`{template: [(type arg, …), …]}` — the instantiations `consumer_src`
    asks for of the named `templates`.

    Read off the CALL SITES, because that is the only place the arguments are
    written.  `demands` walks `consumer_src`'s own statements for a call whose
    callee is a subscript on a bare name (`Pair[Int]()`, `f[Int](x)`) and keeps
    the ones whose base is a declared template.  The shape is recognised by
    `comptime.specialization_name`, which is what
    `formal/model.py::subscript_callee_names` and both backends'
    `_specialization_of` already ask, so there is one recogniser and not three.

    `own` is the consumer's OWN templates and they are skipped.  A call to a
    generic this unit compiles is answered by the local-specialization machinery
    both backends already have (`_specialization_of` →
    `comptime.specialization_name`), so demanding an instantiation of it here
    would publish a second copy of a body the build already emits, under a name
    no importer asked for.

    An argument that is not a concrete type spelling is DROPPED, not refused,
    and the distinction is worth stating: the consumer is not wrong, this module
    simply does not cover that construct (`bugs/FORMAL_generic_monomorph_scope.md`
    names what it is), and a build that refused here would refuse correct Mojo.
    The gap is reported by the export gate or by the bracketed-callee check, both
    of which ask a better question than this one.
    """
    return demands_from_calls(all_instantiation_calls(consumer_src),
                              templates, own)


def demands_key(wanted: dict) -> str:
    """A short, stable digest of a demand set — part of an artifact's identity.

    A module dylib built for `Pair[Int]` is not the same artifact as one built
    for `Pair[String]`: different boundary symbols, different code.  The build's
    output name is content-addressed on the module's own source digest
    (`formal/imports.py::build_module_dylib`), so without this in the name too,
    two programs demanding different instantiations would write over each
    other's library and a program could be linked against a dylib that does not
    export what it binds.  Same reasoning as the source digest that is already
    there, applied to the other half of what makes the artifact what it is.
    """
    import cas                                     # lazy — module docstring
    canon = ";".join(f"{name}[{','.join(args)}]"
                     for name in sorted(wanted or {})
                     for args in sorted(wanted[name]))
    # The EMPTY set digests to the empty string, and that is deliberate rather
    # than a special case: the digest is part of a dylib's output NAME, so a
    # real hash there would rename every module dylib in the tree — moving every
    # cached library, invalidating every CAS entry that recorded one, and
    # changing the path a dependency's load command names for a build that
    # asked for no instantiations at all.  "" is the right answer for the empty
    # demand set: the two libraries would be identical, so they should share a
    # name.
    return cas.hash_parts(canon.encode())[:12] if canon else ""


# ── generated sources ───────────────────────────────────────────────────


def publish_source(mangled: str, concrete: str) -> str:
    """Write one instantiated definition into the CAS; return its path.

    Content-addressed and atomic (`cas.publish`'s own contract: a private temp
    file then `os.replace`), so a concurrent build of the same instantiation is
    harmless and a reader never sees a half-written file.  The path has to be a
    real file on disk because the dylib build is path-driven end to end — it
    reads the source, derives the module prefix from the path, and reports
    diagnostics by line number — and a generated definition that went through a
    different channel would have to re-implement all three.
    """
    import cas                                     # lazy — module docstring
    return cas.publish("formal-mono/" + cas.hash_parts(concrete.encode()),
                       ".mojo", concrete.encode())


def instantiate_all(module_src: str, wanted: dict) -> tuple:
    """`([(template, mangled, args, path), …], [(name, args, reason), …])`.

    The whole of what both callers need, in one place, because the two halves of
    this file are not independent: the importing side has to produce the SAME
    instantiated declarations the exporting side compiles, or the call binds a
    symbol the library never emitted.  Sharing the loop that produces them is
    what makes that structural rather than a convention.

    The TEMPLATE NAME is in the tuple as well as the mangled one because the
    importing side's rewrite key is `(base, args)` — the spelling the source
    used — and recovering the base from the mangled name would be a second
    mangling rule to keep in step with the first.

    A demand that cannot be satisfied comes back in the SECOND list, with its
    reason, rather than raising.  Both callers have a better question to ask
    about it than this module does — `no_public_api_reason` names the shape of
    the module that asked for it, and the bracketed-callee check names the call —
    and a build that raised here would report a demand's failure in place of
    either of those, which is the "message that is false about the file" defect
    `FORMAL_known_limits.md` exists to prevent.
    """
    made, failed = [], []
    for name in sorted(wanted or {}):
        for args in sorted(wanted[name]):
            try:
                mangled, concrete = instantiate(module_src, name, args)
            except MonomorphError as e:
                failed.append((name, tuple(args), str(e)))
                continue
            made.append((name, mangled, tuple(args),
                         publish_source(mangled, concrete)))
    return made, failed


def rewrite_instantiation_calls(stmts, demap: dict) -> int:
    """Rewrite `Base[Args](…)` call sites to the mangled `Base_Args`, in place.

    `demap` is `{(base, (arg, …)): mangled name}` — the same key
    `all_instantiation_calls` produces, and the same table the exporting side
    compiled from, so a call site rewritten here names a definition the library
    on the link line actually has.  Returns the number of call sites rewritten,
    which is what the caller asserts on: a demand that produced a declaration and
    no rewrite (or the reverse) is a bug in the table, and the count is how that
    would be noticed.

    On the AST, not the text.  `Pair[Int]` inside a comment, a docstring or an
    `` `…` `` MLIR literal is not a call, and a textual rewrite would have had to
    re-implement the tokenizer's knowledge to leave it alone; the parser has
    already thrown those away, so there is nothing here to corrupt.  The
    replacement node carries the ORIGINAL's line and column, because every
    diagnostic downstream reports position and a substitution that moved the
    callee to line 0 would send the reader to the top of the file.

    Only a call whose callee is the subscript itself.  A subscript in a value
    position (`len(List)`, `var xs: Pair[Int]`) is not a constructor and is left
    exactly as it was, which is the same distinction
    `formal/model.py::subscript_callee_names` exists to make — see its own
    docstring for why exempting by NAME rather than by position exempts every
    read of that name in the function.  What a bare type ANNOTATION binds to is
    not covered here; `bugs/FORMAL_generic_monomorph_scope.md` records it.

    The position copied onto the replacement is the SUBSCRIPT'S BASE's, not the
    subscript's: `fire_compiler.Parser` leaves `SubscriptExpr.line`/`col` at 0
    (measured — the whole expression is positioned by its `obj`), so copying the
    subscript's own position would report every rewritten call at line 0.

    The bracket is read through the same scope-aware `_bracket_type_args` the
    demand walk uses, for the same reason and with the same consequence: a call
    site whose bracket names a VALUE (`Pair[t]()` with `var t = Float64`) has no
    entry in `demap`, so it is left alone and keeps its brackets to be refused
    with the sentence that is true of it.  Reading the bracket differently here
    than in `all_instantiation_calls` would be the one way a rewrite could name a
    definition the library was never asked for.
    """
    from formal import model as M                  # lazy — cycle
    from formal.build import _names_bound_in       # lazy — cycle
    module_level = set(M.collect_module_symbols(stmts) or {})
    n = 0
    for st in stmts:
        values = _names_bound_in(st) \
            if isinstance(st, F.FunctionDef) else module_level
        for node in M.iter_nodes(st):
            if not isinstance(node, F.CallExpr):
                continue
            base = _callee_base(node)
            if base is None:
                continue
            args = tuple(_bracket_type_args(node.func, values))
            mangled = demap.get((base, args))
            if mangled is None:
                continue
            node.func = F.IdentExpr(name=mangled,
                                    line=getattr(node.func.obj, "line", 0),
                                    col=getattr(node.func.obj, "col", 0))
            n += 1
    return n


def _consumer_statements(consumer_src: str) -> list:
    """`consumer_src`'s top-level statements, from ONE parse.

    The parse goes through `formal.build.parse_module`, the same front end both
    dylib and executable builds use, so the nodes here are the ones the rest of
    the pipeline sees — including the `with_filename` that puts line numbers on
    them.  A file this cannot parse raises out of the caller, which is right: a
    consumer whose own parse failed has a more fundamental problem than a demand
    for an instantiation, and swallowing that here would turn a parse error into
    an empty demand set and then into "that module exports nothing".
    """
    from formal.build import parse_module          # lazy — cycle
    return parse_module(consumer_src)


def _callee_base(call):
    """The bare name a call's SUBSCRIPT callee applies to, or None.

    Delegates to `mojo.middle.comptime.specialization_name`, which is the one
    recogniser of `f[a, b](…)` → `f` that both backends already ask
    (`formal/arm64_codegen._specialization_of` forwards to it).  Asking it here
    rather than re-testing `isinstance(func.obj, F.IdentExpr)` is what keeps a
    dotted specialization `mod.f[T](…)` out of this module's demand set: it
    answers None for that shape by design, and a demand this module then tried
    to satisfy would be attributed to the wrong module.
    """
    import mojo.middle.comptime as comptime_eval    # lazy — module docstring
    return comptime_eval.specialization_name(getattr(call, "func", None))


def _bracket_type_args(sub, values=()) -> list:
    """The bracket's items as concrete type-argument spellings, or [].

    A COMMA LIST is several arguments and not one: `Pair[Int, Bool]` is `Pair`
    declared with two parameters, and joining the items into `Int_Bool` would
    hand the arity check in `instantiate` a single argument against a two-
    parameter declaration and then report the arity as the problem when the
    source got it exactly right.  So a `TupleExpr`/`ListExpr` index is expanded
    here, where the bracket's meaning is known, and `type_arg_text` has no tuple
    arm at all — a type argument is one item and the only way to write several is
    the bracket.

    A KEYWORD bracket (`f[T = Int](…)`) carries its items in `attrs` and not in
    `index` (the parser's own split, `mojo/middle/comptime.keyword_bracket_args`
    documents it), and a keyword bracket is not read here: binding it positionally
    against a declaration that is a lossy record is what that function's own
    docstring warns against, and an unrecognised item here would be mangled into
    a name no importer computed.  `bracket_items` is that decision, in one place
    both readers of this bracket now share.
    """
    spelled = [type_arg_text(i, values) for i in bracket_items(sub)]
    return spelled if spelled and all(spelled) else []


def bracket_items(sub) -> list:
    """The bracket's ITEMS, a comma list expanded, or [] when there is none.

    The ONE reader of a specialization's bracket, and both of its consumers are
    here rather than beside the emitter that needs them: `demands` below, which
    asks whether the items spell concrete TYPE arguments, and
    `supplied_bracket_args`, which asks what a call site SUPPLIED for a callee
    with no declaration to bind them against.  Two readings of one bracket is
    how the two answers come to disagree about `f[a, b](x)` — and the second
    one is the arm whose disagreement is a wrong value rather than a missing
    demand, because it becomes leading ARGUMENTS.

    `[]` for a callee that is not a subscript at all (`f(x)`), and for a
    KEYWORD bracket (`f[a = 1](x)`), which the parser keeps in `attrs` and not
    in `index`.  The keyword half is not answered here for the reason
    `_bracket_type_args` gives: binding it needs the callee's declared
    comptime-parameter names, and a value callee has no declaration — so
    `model.value_call_keyword_refusal` is what a keyword bracket on one of
    those is, rather than a positional guess here.
    """
    if sub is None or getattr(sub, "attrs", None):
        return []
    if not isinstance(sub, F.SubscriptExpr):
        return []
    index = sub.index
    return list(index.elements) if isinstance(
        index, (F.TupleExpr, F.ListExpr)) else [index]


def supplied_bracket_args(call) -> list:
    """`f[a, b](x)` → `[a, b]`; `f(x)` → `[]`.  What the brackets SUPPLIED.

    The bracket-to-arguments half of a specialization, for the callee whose
    declaration this build does not have: a call through a FUNCTION VALUE, where
    the word being called is the only callee there is and nothing declares its
    comptime parameters.  On both architectures a comptime parameter is an
    ordinary LEADING argument (`comptime.param_names` says so), so the items
    the source wrote in brackets are the arguments it expects first, in bracket
    order, evaluated in the CALLER's scope — which is what makes
    `workgroup_function[tile_size](offset)` and `workgroup_function(tile_size,
    offset)` one lowering rather than two.

    **Why it is not `comptime.specialization_args`, which is the reader for
    every other specialization on this path.**  That one binds the items to a
    DECLARED list: it pads a short bracket with 0 and truncates a long one to
    the declaration's length, because a named generic's parameter list is a
    fact both ends hold.  Here there is no list, so there is nothing to pad
    against and nothing may be truncated — the source wrote some arguments, and
    they are passed, because the alternative is inventing an arity for a
    function this build cannot read.  `f[3](x)` therefore reaches the callee as
    `f(3, x)` and `f(x)` as `f(x)`; a callee that wanted a comptime parameter
    the bracket did not supply is a program whose two ends disagree, and it
    reads whatever the register held, exactly as a direct call to a generic
    with too few arguments does.

    Also why it is not the parser's own `index`: a comma list is several
    arguments, and this is the place the bracket's meaning is known, so the
    expansion happens here (`bracket_items`) rather than in each reader.
    """
    return bracket_items(getattr(call, "func", None))