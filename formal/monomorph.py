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
the `b8` round of `bugs/FORMAL_sweep_work_map.md` §4.1: past every codegen refusal
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
import copy

import fire_compiler as F


class MonomorphError(Exception):
    """A demand this module cannot satisfy, with the reason in one sentence."""


#: `{template: reason}` for the demands the build in flight could not satisfy —
#: one entry per template, the FIRST reason it failed with.
#:
#: A demand that fails leaves its call site carrying brackets, and the
#: bracketed-callee scan (`formal/build.py::check_module_symbols`) is what
#: refuses it. Without this table the scan can only say the generic
#: `specialization_call_refusal` — "a call arriving here asked for none" — which
#: is FALSE of a call whose bracket named a type argument perfectly well and
#: whose demand failed for a stated reason (arity, a non-concrete argument, or a
#: trait-bound violation). The scan asks this table first and uses the reason
#: when there is one, so the reader gets the diagnostic the instantiation owes
#: instead of a sentence about a missing demand.
#:
#: Module-level, like `formal/model.py::_MODULE_SYMBOLS` and for its reason: the
#: consumer (the scan) is in another module and holds no unit of its own. It is
#: cleared per UNIT (`clear_failed_demands`), because two modules compiled in
#: one process — a dylib and its dependent — must not answer for each other's
#: failed demands.
_FAILED_DEMANDS: dict = {}


def clear_failed_demands() -> None:
    """Forget the previous unit's failed demands. Called at the start of a build."""
    global _FAILED_DEMANDS
    _FAILED_DEMANDS = {}


def failed_demand_reason(template: str) -> str | None:
    """The reason `template`'s instantiation failed in this unit, or None.

    Asked by the bracketed-callee scan about the base name of a call it cannot
    bind; `None` means the failure (if any) is not one this module recorded, and
    the scan keeps its own generic refusal."""
    return _FAILED_DEMANDS.get(template)


def _record_failed_demands(failed) -> None:
    """`setdefault` each `(template, args, reason)` into `_FAILED_DEMANDS`.

    First reason wins, so the message is stable across the order the demand set
    happened to be walked in."""
    for name, _args, reason in failed or ():
        _FAILED_DEMANDS.setdefault(name, reason)


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
    return list(_derived_from_source("template_names", src,
                                     lambda: _template_names_of(src)))


def _template_names_of(src: str) -> tuple:
    """The body of `template_names`, computed once per source text: the export
    rule's generic names plus the variadic functions (`*args`), which are
    specialized per call-site arity.  The variadic scan parses `src`, so it
    lives INSIDE the memoized computation — outside it, every caller paid a
    whole-module parse per call (a bare-call walk asks once per call node)."""
    import reflect                                  # lazy — see the module docstring
    from formal.build import parse_module
    out = sorted(name for name, why in reflect.export_exclusions(src).items()
                 if why == reflect.EXCL_GENERIC)
    try:
        for st in parse_module(src):
            if isinstance(st, F.FunctionDef) and st.name not in out and any(
                    isinstance(p, (list, tuple)) and p and isinstance(p[0], str)
                    and p[0].startswith('*') and not p[0].startswith('**')
                    for p in (getattr(st, 'params', None) or [])):
                out.append(st.name)
        out = sorted(set(out))
    except Exception:
        pass
    return tuple(out)


def template_struct_names(src: str) -> list:
    """The names in `template_names(src)` that are STRUCT templates.

    The subset that matters to `formal/model.py::subscript_index_is_a_comptime_
    parameter_list`: a bracket on a struct template's name is an explicit
    parameter list, a bracket on a function template's name is a comptime
    specialization both backends answer locally. `template_kind` is the one
    reader of the distinction (`without_template_bodies` asks it the same way),
    and it may raise `MonomorphError` for the export rule's one known
    imprecision — a nested `def name[…]` inside a function body — so a name no
    extractor can pull out is skipped rather than propagated: this is a
    DIAGNOSIS aid, and a name that is not really a template must not turn a
    build into a crash.

    Both halves it composes are already memoized on the source text
    (`template_names` and `template_kind`), so a build asks each of them once
    however many front ends call this.
    """
    out = []
    for name in template_names(src):
        try:
            kind = template_kind(src, name)
        except MonomorphError:
            continue
        if kind == KIND_STRUCT:
            out.append(name)
    return out


def _template_call_shapes(src: str) -> tuple:
    """`(bare, bracketed)` template names in `src`, from ONE parse of it.

    `bare` is a name a `Name(...)` construction CALLS; `bracketed` is a name a
    `Name[...]` SUBSCRIPT applies to. The two decide whether an unused-parameter
    struct template may be kept (see `_layout_independent_struct`), and the
    distinction is not cosmetic: an explicitly instantiated template must still
    be DROPPED so the instantiation and the bracketed-callee refusal keep their
    meanings. Measured — keeping `struct Triple[A: AnyType, B: AnyType,
    C: AnyType]` because its parameters are unused made
    `type_argument_list_on_a_struct_this_unit_declares` refuse with a different
    sentence, because `Triple[Int, s, False]` is then a recognized struct
    instead of an unclassifiable bracket.

    The walk is over the WHOLE statement list, so a construction inside a
    function body counts, and it reads the AST rather than the text, so a
    bracket in a comment or a docstring does not. A name used BOTH ways is
    `bracketed` and is dropped: the explicit path owns it, and mixing the two is
    the inference feature the `FORMAL generic local binding has no home` bug
    records.
    """
    import fire_compiler as F                      # lazy — the AST classes
    from formal import model as M                  # lazy — cycle
    bare: set = set()
    bracketed: set = set()
    for st in _consumer_statements(src):
        for node in M.iter_nodes(st):
            if not isinstance(node, F.CallExpr):
                continue
            fn = node.func
            if isinstance(fn, F.IdentExpr):
                bare.add(fn.name)
            elif isinstance(fn, F.SubscriptExpr) \
                    and isinstance(fn.obj, F.IdentExpr):
                bracketed.add(fn.obj.name)
    return bare, bracketed


def _layout_independent_struct(src: str, name: str) -> bool:
    """Whether struct template `name`'s layout is independent of its type args.

    A generic struct whose type parameters occur NOWHERE in its body — no field
    and no method mentions them — has a layout that does not depend on the
    arguments, so its own declaration IS a valid layout and a BARE construction
    of it (`Marker(b.a)`, no bracket) is well defined. `without_template_bodies`
    drops every struct template because a body that READS a bracket parameter has
    no value behind it; this is the case that reads none.

    `struct Marker[T: AnyType]: var v: Int` is the shape: `T` is in the head and
    nowhere else. Measured on both architectures — a bare `Marker(b.a)` was
    refused (`'m.v' is a field access through 'm'`, the binding never classified
    because the template had been dropped) while the same program with
    `Marker[Int]` built and answered 7. With the template kept,
    `structs_by_name` has it and `_one_word_constructor_bindings` classifies the
    local, which is the whole of what was missing. The interpreter and the gimple
    path already answer the bare form, so this is the formal path catching up
    rather than a new construct.

    Conservative on two axes, and both are load-bearing:

      * every bracket parameter must be a TYPE parameter (`T: AnyType`). A
        COMPTIME parameter (`struct Box[T: AnyType, keys: List[T]]`) supplies a
        value the body may read, so its instantiation is not optional and the
        template must still be dropped — measured: keeping `Box` made
        `comptime_binding_with_a_literal_value_still_builds` refuse on a method
        call, because the instantiation and the template then disagree about the
        struct. A parameter with any other annotation — a comptime type, a trait
        bound — returns False and is dropped as before.
      * a type parameter that occurs in the body AT ALL — even in a position the
        layout discards, like a pointer's origin (`elaborate.erased_only_params`)
        — returns False, so only the templates whose body cannot mention a
        parameter, and therefore cannot fail on one, are kept.

    A type parameter that IS used (`struct Pair[T]: var a: T` built bare) is a
    real inference, still refused, and is the remainder the
    `FORMAL generic local binding has no home` bug records.
    """
    import re
    import elaborate
    tmpl = _template_source(src, name, KIND_STRUCT)
    if tmpl is None:
        return False
    head = elaborate.mm.head_match(tmpl)
    if not head:
        return False
    params = []
    for p in elaborate.split_top_level_commas(head.params):
        p = p.strip()
        if not p or elaborate._is_param_marker(p):
            continue
        name_part, sep, ann = p.partition(":")
        if not sep or ann.strip() != "AnyType":
            return False
        params.append(name_part.strip())
    if not params:
        return False
    code = elaborate._code_only(tmpl)
    return not any(re.search(rf"\b{re.escape(p)}\b", code) for p in params)


def without_template_bodies(stmts: list, src: str, keep=()) -> list:
    """`stmts` with this source's GENERIC TEMPLATE declarations removed.

    **A template's own body is not in any image, so compiling it is work with no
    consumer and a refusal waiting at the end of it.** The instantiated bodies
    are: `instantiate_all` writes each one out (`publish_source`) and both paths
    compile those instead — `formal/imports.py::_instantiated_sources` hands them
    to `compile_formal_dylib` as extra sources, and its `_own_instantiations`
    appends their statements to the executable's own. What is left over is the
    declaration itself, and that is the thing this drops.

    The measurable cost of not dropping it, and it is a REFUSAL rather than a
    wasted pass: the template body is analysed with no instantiation in scope, so
    a read of a bracket parameter has no value behind it. Measured on this tree,
    both architectures, `struct Box[T: AnyType, keys: List[T]]` with
    `def total(self) -> Int: return self.first + len(Self.keys)`:

        build: len(Self.keys) — the source does not say what this operand holds,
        and on this path the two things len() can answer are told apart by what
        the operand IS …

    — and `std/collections/type_dict.mojo`'s `comptime length = len(Self.values)`
    is the same shape and is the reason this is not a two-line curiosity.

    **The set of names comes from `template_names`, which is the EXPORT RULE's own
    answer** (`reflect.EXCL_GENERIC`), not from a second reader of the source. So
    "a template is not an API" is asked before the body is compiled rather than
    after, which is the order the export table already implied: the name was never
    going to be exported, and now its body is never going to be analysed either.

    `keep` names to leave alone, and the one caller that has one is the module
    path: a library's manifest records the instantiations it published, and that
    is computed from the source rather than from this list, so nothing here needs
    an escape hatch today. It exists so a future caller that DOES have one says
    which name rather than reaching around this function.

    A fresh list, never the caller's, for the reason `_rewritten_own_statements`
    gives about the memoised parse: these nodes are shared with every other reader
    in the process, and a template removed from one build's view of them would be
    gone from the next build's too.

    **A struct template whose type parameters are all PHANTOM need not be
    dropped, and an executable keeps it** — via `keep=concrete_struct_templates(
    src)`. Its body mentions none of the parameters, so dropping the `[…]` from
    the source yields a declaration that is already concrete: no bracket read
    behind any name and nothing for `instantiate` to substitute. Keeping it is
    what lets an un-bracketed construction of it (`Marker(b.a)`, the type
    argument inferred or annotated rather than spelled in the call) bind a home —
    the defect `FORMAL generic local binding has no home` records. The
    LIBRARY path deliberately does not pass it: a kept declaration becomes part
    of `_method_exports`' source set, so it would publish the template's methods
    under the template's own name, and changing a dylib's export surface is not
    a decision to make from this row.
    """
    import fire_compiler as F                        # lazy — the AST classes
    bare, bracketed = _template_call_shapes(src)
    drop = {n for n in template_names(src)
            if template_kind(src, n) == KIND_STRUCT
            and not (n in bare and n not in bracketed
                     and _layout_independent_struct(src, n))} - set(keep or ())
    if not drop:
        return stmts
    return [s for s in stmts
            if not (isinstance(s, F.StructDef)
                    and getattr(s, "name", None) in drop)]


def concrete_struct_templates(src: str) -> set:
    """The STRUCT templates whose type parameters are ALL phantom.

    A phantom parameter (`elaborate.phantom_type_params`) occurs nowhere outside
    the generic head, so the declaration is what it would be for any argument:
    dropping the `[…]` yields a valid concrete `struct`, with no bracket
    parameter for the body to read and nothing for `instantiate` to substitute.
    Such a template therefore needs no instantiation at all to be compiled, and
    the names are exactly the ones a caller of `without_template_bodies` should
    pass as `keep` (the executable path does; see that function's docstring for
    why the library path does not).

    Read from the SOURCE for the same reason `template_names` is: the question
    is a property of the declaration text and the extractors
    (`_template_source`) are the one reader of it. A name `template_kind` filed
    as a struct but neither extractor can pull out is skipped rather than
    refused here: it is the nested-`def` imprecision `template_kind`'s own
    docstring names, and this function is asking whether to KEEP a declaration,
    not whether the source is well formed.

    **A name the source applies with BRACKETS is excluded**, even when phantom,
    and `_bracketed_callee_bases`'s own docstring carries the measurement: a
    bracketed application is answered by the instantiation machinery or by the
    refusal the bracket earns, and keeping the declaration as well moves the
    answer. The case this function exists for is the UN-bracketed one —
    `Marker(b.a)` — where no other mechanism names the type.
    """
    import elaborate                                # lazy — see module docstring
    structs = [n for n in template_names(src)
               if template_kind(src, n) == KIND_STRUCT]
    if not structs:
        return set()                 # no bracket walk for a module with none
    bracketed = _bracketed_callee_bases(src)
    out = set()
    for name in structs:
        if name in bracketed:
            continue
        try:
            tmpl = _template_source(src, name, KIND_STRUCT)
        except MonomorphError:
            continue
        params = elaborate.type_param_names(tmpl)
        if params and len(elaborate.phantom_type_params(tmpl, params)) == len(params):
            out.add(name)
    return out


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


def split_variadic_params(params):
    """`(fixed, variadic_or_None)` for a template's bracket-parameter names.

    **A `*name` parameter is one declaration with an ARITY, and treating it as
    one name is what made `Pair[Int, 1, 2, 3]` un-instantiable.** Mojo's bracket
    head is a parameter list (`elaborate.type_param_names`' own docstring), and
    `*values: T` declares a parameter that takes any number of arguments — so
    `std/collections/type_dict.mojo`'s own use site,
    `TypeDict[T=Int, Trait=AnyType, [1,2,3], Int, String, Float64]`, supplies
    SIX arguments against four declared names and is not malformed. Read as four
    names it was refused for arity, with a message that told the reader to take
    the arguments as named parameters — which is the program rewritten, not the
    program answered.

    Only a LAST `*name` counts, because that is where a Python-like parameter
    list puts a variadic and because a `*name` followed by more names is a
    syntax this path does not accept a bracket spelling for. `**kwargs` is
    returned with its OWN star so the caller can refuse it BY NAME rather than
    bind it: a bracket argument is a POSITIONAL spelling and a keyword
    collection is not one, so the extra-argument rule has no reading for it.
    """
    if params and params[-1].startswith("**"):
        return params[:-1], ("**", params[-1][2:])
    if params and params[-1].startswith("*"):
        return params[:-1], ("*", params[-1][1:])
    return params, None


def _variadic_binding(name, args):
    """The substitution text for a `*name` parameter bound to `args`.

    A tuple display, and nothing else: the parameter's value at run time is a
    SEQUENCE of the arguments the use site supplied, and a tuple display is the
    one spelling in this tree that is a sequence of expressions with a length
    the reader can count. `()` for none — a `*values` bound to nothing is the
    empty sequence, and `len(())` is 0 rather than a subscript into a name
    nothing declared.

    **The arguments are the consumer's own spellings, already validated as type
    arguments** (`type_arg_text`, which every bracketed use site goes through
    before it becomes a demand), so this cannot splice a computed expression
    into a declaration. That is the reason it is a tuple of the same strings
    rather than a re-parse of anything.
    """
    return "(" + ", ".join(args) + (",)" if len(args) == 1 else ")")


#: A bracket-argument spelling that is a bare compile-time VALUE literal rather
#: than a type: an integer/float/string/bool/None literal, optionally signed.
#: Matches what `_display_element_text` produces for a literal, and NOTHING a
#: type spelling (`Int`, `simd.float32`, `List_Int`) or a display (`[1, 2, 3]`,
#: `(4, 5)`) produces — so a display keeps the type-argument reading it has
#: always had and only a BARE literal turns on `type_param_kinds`.
_BARE_VALUE_RE = re.compile(
    r"""(?:[+-]?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|inf|nan)
        |True|False|None
        |'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")""", re.VERBOSE)


def _arg_is_bare_value(text: str) -> bool:
    """True when `text` is a bare compile-time value literal, not a type."""
    return bool(text) and _BARE_VALUE_RE.fullmatch(text) is not None


def instantiate(src: str, name: str, args) -> tuple:
    """`(mangled_name, concrete_source)` for `name[args]` inside `src`.

    `args` is the consumer's own spelling of the type arguments, in bracket
    order, and it is checked against the template's DECLARED parameter count
    before anything is substituted: a bracket with the wrong arity is not an
    instantiation of this template, and mangling it anyway would publish a
    symbol whose body was built from a parameter the source never bound.

    **A VARIADIC parameter is exempt from the exact count, and only it.**
    `split_variadic_params` is the one reader of the distinction; this function
    asks it and then checks what it left. The refusal that survives is the one
    that is still true: too FEW arguments is a bracket that cannot bind the
    declaration, whatever the declaration says.
    """
    import elaborate, monomorphize                 # lazy — module docstring
    args_list = [str(a) for a in args]
    # Check if this is a variadic function specialization request
    if args_list and len(args_list) == 1 and args_list[0].startswith('__variadic_') and args_list[0].endswith('__'):
        try:
            arity_str = args_list[0][len('__variadic_'):-len('__')]
            # Could be just extras, or extras_fixed
            if '_' in arity_str:
                extras_str, fixed_str = arity_str.split('_')
                extras = int(extras_str)
                fixed_orig = int(fixed_str)
            else:
                extras = int(arity_str)
                fixed_orig = None
        except Exception:
            extras = 0
            fixed_orig = None
        arity = extras
        # Handle variadic function specialization
        try:
            kind = template_kind(src, name)
        except Exception:
            kind = KIND_FN
        try:
            template_src = _template_source(src, name, KIND_FN)
        except Exception:
            raise MonomorphError(f"no fn template {name!r} for variadic specialization")
        # Use monomorphize.mangle for the mangled name
        mangled = monomorphize.mangle(name, {"__variadic_arity": str(extras)})
        # Parse and rewrite the function
        try:
            from formal.build import parse_module
            import fire_compiler as F
            from formal import model as M
            stmts = parse_module(template_src)
            # Find the function
            fn = None
            for st in stmts:
                if isinstance(st, F.FunctionDef) and st.name == name:
                    fn = st
                    break
            if fn is None:
                raise MonomorphError(f"could not find function {name}")
            # Determine variadic param name and fixed params
            var_name = None
            fixed_params = []
            for pentry in getattr(fn, 'params', []) or []:
                if isinstance(pentry, (list, tuple)) and pentry:
                    pname = pentry[0]
                    if isinstance(pname, str):
                        if pname.startswith('**'):
                            break
                        elif pname.startswith('*') and not pname.startswith('**'):
                            var_name = pname[1:] if len(pname) > 1 else pname
                            break
                        else:
                            fixed_params.append(pentry)
            if var_name is None:
                raise MonomorphError(f"{name} is not variadic")
            # Create new function with fixed + extra params
            new_params = list(fixed_params)
            for i in range(extras):
                new_params.append((f'{var_name}_{i}', None))
            new_fn = F.FunctionDef(
                name=mangled,
                params=new_params,
                body=list(fn.body or []),
                return_type=getattr(fn, 'return_type', None),
                kwonly=getattr(fn, 'kwonly', None),
                param_has_default=getattr(fn, 'param_has_default', None),
                param_defaults=getattr(fn, 'param_defaults', None),
                decorators=getattr(fn, 'decorators', None),
                line=getattr(fn, 'line', 0),
                col=getattr(fn, 'col', 0),
            )
            # Rewrite body: len(var_name) -> extras, var_name[i] -> var_name_i
            new_body = []
            for node in new_fn.body:
                new_body.append(_rewrite_variadic_node(node, var_name, extras))
            new_fn.body = new_body
            # Render back to source (simple approach)
            concrete = _render_function(new_fn)
            return mangled, concrete
        except MonomorphError:
            raise
        except Exception as e:
            raise MonomorphError(str(e))
    kind = template_kind(src, name)
    template_src = _template_source(src, name, kind)
    params = elaborate.type_param_names(template_src)
    if not params:
        raise MonomorphError(
            f"{name!r} is excluded from the export set as a generic template "
            f"but its declaration has no type parameter, so there is nothing to "
            f"substitute and no instantiation is a different function")
    args = args_list
    fixed, variadic = split_variadic_params(params)
    if variadic is not None and variadic[0] == "**":
        raise MonomorphError(
            f"{name}[{', '.join(args)}] supplies {len(args)} type "
            f"argument{'s' if len(args) != 1 else ''} but `{name}` declares "
            f"{len(params)} ({', '.join(params)}), and `**{variadic[1]}` is a "
            f"keyword collection: a bracket argument is a POSITIONAL spelling "
            f"and there is no positional spelling for one of these. Name the "
            f"arguments the declaration takes and pass the collection as a "
            f"value, which is the same program with a representation")
    too_few = len(args) < len(fixed)
    too_many = variadic is None and len(args) > len(fixed)
    if too_few or too_many:
        raise MonomorphError(
            f"{name}[{', '.join(args)}] supplies {len(args)} type "
            f"argument{'s' if len(args) != 1 else ''} but `{name}` declares "
            f"{len(params)} ({', '.join(params)}); an instantiation is one "
            f"template specialized for exactly the arguments it declares"
            + ("" if too_few else
               f" — a `*` parameter would take the extra one"
               f"{'s' if len(args) - len(fixed) != 1 else ''} and this "
               f"declaration has none"))
    # A BARE LITERAL is a compile-time VALUE, and only a VALUE parameter can
    # take one.  This is the check that lets the demand walk carry a literal
    # without turning `Pair[2]` (a value in a TYPE's position) or `tile[2, 3]`
    # (a FUNCTION's value specialization, which the local machinery already
    # answers) into a boundary symbol — see `value_demands_for` below, which
    # offers exactly this instantiation as the admission test.
    #
    # Only the FIXED parameters are asked: a `*values: T` declaration collects
    # any number of arguments and `_variadic_binding` already binds them as a
    # tuple display, so a literal in the variadic TAIL is the existing
    # behaviour (`Pair[T: AnyType, *values: T]` at `Pair[Int, 1, 2, 3]`) and
    # not this check's business.
    bare = [i for i, a in enumerate(args) if i < len(fixed)
            and _arg_is_bare_value(a)]
    if bare:
        if kind == KIND_FN:
            raise MonomorphError(
                f"{name}[{', '.join(args)}] is a comptime specialization of a "
                f"FUNCTION template, and a value specialization of a function "
                f"is a call site binding, not a boundary symbol: both backends "
                f"already lower it through "
                f"`mojo/middle/comptime.specialization_args`, so demanding an "
                f"instantiation here would publish a second copy of a body the "
                f"build already emits under its own name.  This is not a "
                f"refusal of the program — the call keeps its brackets and the "
                f"local machinery answers them")
        kinds = elaborate.type_param_kinds(template_src)
        for i in bare:
            if i < len(kinds) and kinds[i] != "value":
                raise MonomorphError(
                    f"{name}[{', '.join(args)}] binds the literal `{args[i]}` "
                    f"to `{params[i] if i < len(params) else '?'}`, which its "
                    f"declaration annotates as a TYPE parameter.  A value in a "
                    f"type's position is not an instantiation of this template: "
                    f"substituting `{args[i]}` for a type would produce a "
                    f"definition built from an argument the source cannot mean, "
                    f"and a boundary symbol for it would let a later call bind "
                    f"that body.  Use a type here, or declare the parameter "
                    f"with a value type (`{args[i]}`'s own kind) if a comptime "
                    f"value is what it names")
    targs = dict(zip(fixed, args[:len(fixed)]))
    if variadic is not None:
        targs[variadic[1]] = _variadic_binding(variadic[1],
                                              args[len(fixed):])
    try:
        import elaborate
        elaborate.check_bounds(src, template_src, targs)
    except elaborate.ConformanceError as e:
        raise MonomorphError(str(e)) from None
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
    """The ABI spelling of a bracket ARGUMENT, or "" when there is not one.

    "" is the answer for everything that is not a spelling, and it is a refusal
    rather than a fallback: a computed argument has no single name, and
    inventing one is how a call binds another instantiation's body (the reason
    `no_public_api_reason` refuses to export a template under its base name).
    The accepted shapes are the three a TYPE argument is written in:

        `Int`            an identifier
        `simd.float32`   a dotted name
        `List[Int]`      a type application, spelled `List_Int` so the mangled
                         name is a legal symbol fragment through the ONE
                         mangler (`monomorphize.safe_suffix`) rather than a
                         second copy of that rule here

    **and ONE value shape, a LITERAL DISPLAY** — `[1, 2, 3]`, `(Int, String)`,
    nested to any depth, with every element itself one of the three above or a
    literal (`_display_element_text` is the one reader).  That is
    `std/collections/type_dict.mojo`'s own use site
    (`TypeDict[T=Int, Trait=AnyType, [1,2,3], Int, String, Float64]`), where
    every parameter is a VALUE, and it was refused by the multi-index rule in
    `formal/model.py` long before the monomorphizer could be asked — so the
    bracket was never a demand and the call was never rewritten.

    **A literal is accepted only INSIDE a display, and the asymmetry is the
    point rather than an accident.**  `tile[2, 3](…)` is a comptime
    specialization of a value parameter, and both backends already answer it
    through `mojo/middle/comptime.specialization_args`; demanding `tile_2_3`
    for it as well would publish a boundary symbol for a specialization the
    build already emitted under its own name.  `Pair[2]` therefore stays a
    non-demand (pinned by `test_formal_monomorph.py`), and what a DISPLAY buys
    is the case where the value is a SEQUENCE, which a specialization bracket
    never is and a boundary symbol has to be able to tell apart.

    **The display's spelling is also its mangling, and it has to be all three
    of stable, legal as a symbol fragment and DISTINCT** — two instantiations
    differing only in a value argument must be two symbols or the second
    overwrites the first.  All three come from the spelling being a FUNCTION of
    the value: `safe_suffix` is injective on the text it is given, so the only
    question left is whether two different displays can render the same text.
    They cannot, because the rendering keeps each element's own brackets and
    each separator, `repr` for a string, and the parenthesised comma for a
    one-element tuple (`(1,)`), so `[1]` and `(1,)` and `1` are three texts and
    therefore three symbols.  The rendering is ALSO the text substituted into
    the body (`monomorphize_source` substitutes it whole-word), which is why an
    element has to be a literal or a type spelling rather than an expression:
    the substituted text has to be the same program.

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
    for this purpose by construction — `Float32` is in none of its four tables,
    so asking it would refuse `Pair2[Float32]()`, which is correct Mojo.  A name that nothing
    binds is a type; a name something binds is a value unless a type is
    declared with that spelling, and the second half of that sentence is the
    documented limit (`bugs/FORMAL_generic_monomorph_scope.md`): a type
    declared in the CONSUMER's own file is refused rather than instantiated.

    `F.IntLiteral` and every expression form are refused at the TOP LEVEL, which
    is also what keeps `tile[2, 3](…)` — a comptime specialization whose bracket
    items are VALUES — from being read as a demand for `tile_2_3`; inside a
    display a literal is a value the argument NAMES, which is the whole
    difference between the two.

    **A bare literal is nevertheless read as a VALUE argument when the same
    bracket also names a TYPE, and `_bracket_type_args` is where that rule
    lives.** `Tagged[Int, 0]()` on `struct Tagged[T, origin: Int]` is
    `FORMAL_an_explicit_parameter_list_naming_a_comptime_value` (literal
    comptime-value argument on a mixed bracket, fixed 2026-10-08) §2 row 4:
    the second element is a comptime VALUE and every other element is a type, so
    the bracket is a cross-module instantiation rather than the all-values
    comptime specialization `tile[2, 3]` is. The substitution itself already
    works (`monomorphize_source` is a whole-word textual substitution and does
    not read a parameter's kind); what was missing was this reader keeping the
    literal, and the asymmetry is deliberate: a bracket that is ENTIRELY values
    stays the local machinery's, and only a mixed one becomes a demand.
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
    if isinstance(expr, (F.ListExpr, F.TupleExpr)):
        return _display_text(expr, values)
    return ""


def _display_element_text(expr, values) -> str:
    """One ELEMENT of a literal display: a literal, or a type spelling.

    Deliberately not `type_arg_text`, which refuses a bare literal because a
    bare literal at the TOP level of a bracket is the `tile[2, 3]` case. Inside a
    display the same node is a value the argument names rather than a
    specialization to be answered by the local machinery, and refusing it would
    refuse `type_dict.mojo`'s own use site.

    The set is closed on purpose — literals, and the three type spellings by
    delegating to `type_arg_text` — because this text is SUBSTITUTED into the
    instantiated body. `f(1)`, `a + b` and `x.y()` have no closed form here and
    would be a second question (what is the value of this expression) asked by
    a function whose whole job is to name one.
    """
    if isinstance(expr, (F.ListExpr, F.TupleExpr)):
        return _display_text(expr, values)
    spelled = type_arg_text(expr, values)
    if spelled:
        return spelled
    if isinstance(expr, F.IntLiteral):
        return str(expr.value)
    if isinstance(expr, F.FloatLiteral):
        return repr(expr.value)
    if isinstance(expr, F.StringLiteral):
        return repr(expr.value)
    if isinstance(expr, F.BoolLiteral):
        return "True" if expr.value else "False"
    if isinstance(expr, F.NoneLiteral):
        return "None"
    if isinstance(expr, F.UnaryOp) and expr.op in ("-", "+"):
        inner = _display_element_text(expr.operand, values)
        return f"{expr.op}{inner}" if inner else ""
    return ""


def _display_text(expr, values) -> str:
    """A list or tuple display as one bracket-argument spelling, or "".

    `""` when ANY element has no spelling, and all-or-nothing on purpose: a
    partial display would substitute a body built from half the values the
    source wrote, which is the fabricated-answer outcome this module refuses
    everywhere else.

    The one-element tuple keeps its comma. `(1)` in the substituted body is the
    integer `1`, so a one-element tuple has to render as `(1,)` to stay the
    tuple the source wrote — and the same character is what keeps it a
    different symbol from the list `[1]` and from the bare `1`.
    """
    items = [_display_element_text(e, values) for e in (expr.elements or ())]
    if not items or not all(items):
        return ""
    body = ", ".join(items)
    if isinstance(expr, F.ListExpr):
        return f"[{body}]"
    return f"({body}{',' if len(items) == 1 else ''})"


def _bracketed_calls_pair(consumer_src: str) -> tuple:
    """`(type-arg map, permissive map)` for `consumer_src`, derived once.

    The ONE walk behind `all_instantiation_calls` and `all_bracketed_calls`:
    they read the SAME top-level statements with the SAME scope bindings and
    differ only in whether a bare literal is a spelling, so computing them
    separately would parse the consumer twice for one demand set.  `derive`
    therefore fills both maps in one pass, and the two public readers take a
    fresh copy of their half (`_derived_from_source` hands back one cached
    object, and `all_instantiation_calls` has always promised fresh lists).

    The walk is per top-level statement rather than one flat walk, because
    "is this identifier a value binding" is a question about the SCOPE the call
    is written in and `iter_nodes` has no parent: `Pair[t]()` is a demand when
    `t` is a type and not one when `t` is the local `var t = Float64` two lines
    above it, and nothing below the callee can tell those apart. So each
    function is walked with its own bindings
    (`formal/build.py::_names_bound_in`) and each module-level statement with
    the module's own table (`formal/model.py::collect_module_symbols`).

    **Once per source text, not once per imported module.**  The parse is still
    made once per call, and the call is still made once per imported module
    (`formal/imports.py::instantiation_demands`) over one unchanged consumer —
    7 extra full parses of a 271 KB `myinterpreter.py` and 22 each of
    `std/simd.mojo`, measured.  The answer is a function of the text alone, so
    it is derived once per distinct text (`_derived_from_source`, whose key and
    bound are documented above `_DERIVED`).
    """
    def derive():
        from formal import model as M                  # lazy — cycle
        from formal.build import _names_bound_in       # lazy — cycle
        stmts = _consumer_statements(consumer_src)
        # The call site spells the name AS BOUND in this unit (`P` for
        # `from pairlib import Pair as P`), and the demand has to name the
        # template the DEFINING module gave it — see `local_defining_names`.
        defining = local_defining_names(stmts)
        syms = M.collect_module_symbols(stmts) or {}
        module_level = set()
        for name, sym in syms.items():
            # Module-level comptime aliases with no literal (e.g. ImmStaticOrigin)
            # must remain passable as value arguments when the declaration expects
            # a value parameter; do not treat them as bound values.
            if getattr(sym, "site", None) == "comptime" and getattr(sym, "literal", None) is None:
                continue
            module_level.add(name)
        typed: dict = {}
        permissive: dict = {}
        tnames = set(template_names(consumer_src))    # once, not per call node
        for st in stmts:
            values = _names_bound_in(st) \
                if isinstance(st, F.FunctionDef) else module_level
            for node in M.iter_nodes(st):
                if not isinstance(node, F.CallExpr):
                    continue
                base = _callee_base(node)
                if base is not None:
                    base = defining.get(base, base)
                    loose = _bracket_all_args(node.func, values)
                    if loose:
                        permissive.setdefault(base, set()).add(tuple(loose))
                    args = _bracket_type_args(node.func, values)
                    if args:
                        typed.setdefault(base, set()).add(tuple(args))
                elif isinstance(node.func, F.IdentExpr):
                    # A bare call to a template this module declares: the type
                    # arguments are inferred from the argument annotations.
                    bname = node.func.name
                    if bname in tnames:
                        inferred = _bare_call_demand(
                            consumer_src, bname, stmts,
                            st if isinstance(st, F.FunctionDef) else None,
                            node, module_level, tolerate_unreadable=False,
                            consumer_src=consumer_src)
                        if inferred:
                            typed.setdefault(bname, set()).add(inferred)
        return ({k: tuple(sorted(v)) for k, v in typed.items()},
                {k: tuple(sorted(v)) for k, v in permissive.items()})
    return _derived_from_source("all_instantiation_calls", consumer_src, derive)


def all_instantiation_calls(consumer_src: str) -> dict:
    """`{base name: sorted([(type arg, …), …])}` — every bracketed callee in
    `consumer_src` whose bracket spells concrete TYPE arguments.

    Unfiltered: it does not know which module declares what, because that is a
    question about the import closure and this is a question about ONE source.
    A program importing `std.collections` reaches thirty modules through its
    package's re-exports (`formal/imports.py::instantiation_demands`), so
    filtering per module by re-parsing the consumer made the cost of a demand
    set a product where it only needed to be a sum.

    A bare literal is deliberately NOT here — that is
    `all_bracketed_calls`'s half — and the asymmetry is the documented one: a
    value at the top level of a bracket is `tile[2, 3]`'s shape, a comptime
    specialization the local machinery answers, and it becomes a boundary
    symbol only when a declaration has a position of a value KIND for it
    (`value_demands_for`).
    """
    return {k: list(v) for k, v in _bracketed_calls_pair(consumer_src)[0].items()}


def all_bracketed_calls(consumer_src: str) -> dict:
    """Like `all_instantiation_calls` but a bare literal IS a spelling.

    A SUPERSET: every entry `all_instantiation_calls` returns is here, plus the
    brackets whose items all have some spelling once a bare literal counts.
    This is the candidate set for a comptime-VALUE argument, and it is not a
    demand set by itself — `Pair[2]` (a value in a TYPE parameter's position)
    and `tile[2, 3]` (a function's value specialization) are both here, and
    `value_demands_for` is what refuses them, by asking `instantiate` whether
    the declaration a module OWNS admits the arguments (`instantiate`'s bare-
    value kind check is the admission test).  Splitting the literal out of the
    strict reader is what keeps the two pinned non-demands above non-demands
    without giving up the `Tagged[Int, 0]` case.
    """
    return {k: list(v) for k, v in _bracketed_calls_pair(consumer_src)[1].items()}


#: A type-argument spelling an ANNOTATION reader will carry into a demand: a
#: bare or dotted identifier and nothing else.  An annotation is a STRING by the
#: time this module sees it (`VarDecl.type_ann`), so the nested-application
#: spelling `List[Int]` — which `type_arg_text` mangles to `List_Int` for a CALL
#: bracket — cannot be converted here without a second copy of that mangling.
#: The conservative direction is to leave it OUT: no demand is invented for a
#: spelling this reader cannot name exactly, and the construction keeps the
#: refusal it has today rather than binding a body under a name nobody computed.
_ANNOTATION_TYPE_ARG_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")


def _declared_types_in_scope(stmts, enclosing_stmt=None) -> dict:
    """`{name: annotation string}` for the names a bare call's arguments can be
    read against: the enclosing function's parameters and `VarDecl`
    annotations, or — at module level — every annotated `VarDecl` in `stmts`.

    The one scope table behind `infer_bare_call`.  A parameter with no
    annotation maps to `None`, and an earlier entry wins over a later
    `VarDecl` of the same name (`setdefault`), exactly as the two copies of
    this table that `derive` and `inferred_demands_for` used to build did.

    Also includes function declarations' return types (16d), so a bare call to
    a function with a declared `->` annotation resolves to that annotation.
    And a `var a = <call>` with no explicit annotation resolves through the
    callee's declared return type.
    """
    from formal import model as M
    declared: dict = {}
    if isinstance(enclosing_stmt, F.FunctionDef):
        for entry in (getattr(enclosing_stmt, "params", None) or []):
            if isinstance(entry, (list, tuple)) and entry:
                declared[entry[0]] = entry[1] if len(entry) > 1 else None
        scope = getattr(enclosing_stmt, "body", None) or []
    elif stmts is None:
        return declared
    else:
        scope = stmts

    # Pass 1: collect function declarations' return types (16d).
    for n in M.iter_nodes(scope):
        if isinstance(n, F.FunctionDef) and getattr(n, "return_type", None):
            declared.setdefault(n.name, n.return_type)

    # Pass 2: collect VarDecl annotations; a call-initialised local with no
    # explicit annotation resolves through the callee's declared return type.
    for n in M.iter_nodes(scope):
        if not isinstance(n, F.VarDecl) or not getattr(n, "name", None):
            continue
        ann = n.type_ann
        if not isinstance(ann, str) or not ann.strip():
            value = getattr(n, "value", None)
            if isinstance(value, F.CallExpr):
                callee = getattr(value, "func", None)
                callee_name = (
                    getattr(callee, "name", None) if isinstance(callee, F.IdentExpr) else None
                )
                if callee_name:
                    ann = declared.get(callee_name)
        if isinstance(ann, str) and ann.strip():
            declared.setdefault(n.name, ann)
    return declared



def _bare_call_arg_annotations(call, declared, scope) -> tuple:
    """([annotation or None per argument], has_literal) for a bare call (16c).
    Keyword arg values that are literals also block inference."""
    ctypes = []
    has_literal = False
    for arg in (getattr(call, "args", None) or []):
        # First, try the direct declaration lookup for simple identifiers
        ann = declared.get(arg.name) if isinstance(arg, F.IdentExpr) else None
        if isinstance(ann, str) and ann.strip():
            ctypes.append(ann)
            continue
            
        # For non-identifier arguments, use _declared_type_of_expr to read from scope
        if isinstance(arg, F.IdentExpr):
            # This is a simple identifier, should have been caught above
            ctypes.append(None)
        else:
            # For transfers (x^), member access (self.f), calls, etc.
            ann = _declared_type_of_expr(arg, scope)
            if isinstance(ann, str) and ann.strip():
                ctypes.append(ann)
            else:
                ctypes.append(None)
        if not isinstance(arg, F.IdentExpr) and type(arg).__name__.endswith('Literal'):
            has_literal = True
    for kw in (getattr(call, "kwargs", None) or []):
        try:
            karg = kw[1]
        except Exception:
            continue
        if not isinstance(karg, F.IdentExpr) and type(karg).__name__.endswith('Literal'):
            has_literal = True
    return ctypes, has_literal


# ── declared-type reading (step 16d: R1) ─────────────────────────────────

def _declared_type_of_expr(expr, scope) -> str | None:
    """The DECLARED type of an expression, read from declarations only — never
    from a body (R1). Returns None when no declaration names it.

    Order (from Q1's chosen reading):
      1. identifier → its declared annotation (parameter, VarDecl, or module-level symbol)
      2. `x^` transfer / `UnaryOp` wrapping an identifier → the identifier's declared type
      3. `self.f` field read → declared field annotation of the enclosing struct
      4. call to a function/ctor with a declared return annotation → that annotation
         (with the callee's own template parameters substituted if the call itself
         was inferred)
      5. a local `var a = <call>` → the call's declared return type (same rule as 4)

    Anything else → None.
    """
    if isinstance(expr, F.IdentExpr):
        return scope.get(expr.name)
    if isinstance(expr, F.UnaryOp) and getattr(expr, "op", None) == '^':
        operand = getattr(expr, "operand", None)
        if isinstance(operand, F.IdentExpr):
            return scope.get(operand.name)
        return None
    if isinstance(expr, F.MemberExpr) \
            and isinstance(getattr(expr, "obj", None), F.IdentExpr) \
            and getattr(expr.obj, "name", None) == "self":
        return scope.get(expr.member)
    if isinstance(expr, F.CallExpr):
        fn = getattr(expr, "func", None)
        callee_name = getattr(fn, "name", None) if isinstance(fn, F.IdentExpr) else None
        if callee_name is None:
            return None
        ret = scope.get(callee_name)
        if isinstance(ret, str) and ret.strip():
            return ret.strip()
    return None


#: `SIMD[T]` / `SIMD[T, w]` as a parameter annotation: the element type binds
#: to the argument's annotation and the width to `1` (a scalar's lane count).
_SIMD_PARAM_RE = re.compile(r'^SIMD\[\s*([^,\[\]]+)\s*(?:,\s*([^,\[\]]+)\s*)?\]$')


def _default_text_is_type_spelling(default: str) -> bool:
    """True when a template-parameter default's text is a type spelling accepted
    by `type_arg_text` (16c).  `Int` / `NoneType` are; `False`, `0` and
    `CompilationTarget.current()` are not."""
    d = (default or "").strip()
    if not d:
        return False
    try:
        from fire_compiler import py_tokenize, Parser
        st = Parser(py_tokenize("x = " + d + "\n")).parse_module()
        if not st:
            return False
        expr = getattr(st[0], "value", None)
        if expr is None:
            return False
        return bool(type_arg_text(expr, set()))
    except Exception:
        return False


def _enclosing_template_params(consumer_stmts, enclosing_stmt, consumer_src) -> set:
    """Type-parameter names of the enclosing template (defect #3)."""
    if not isinstance(enclosing_stmt, F.FunctionDef):
        return set()
    import elaborate
    if isinstance(consumer_src, str) and consumer_src:
        try:
            tmpl = elaborate.extract_fn_source(consumer_src, enclosing_stmt.name)
            if tmpl:
                return set(elaborate.type_param_names(tmpl))
        except Exception:
            pass
    return set()


def _inferred_binding_ok(binding, enclosing_tparams) -> bool:
    """Reject a result that is the caller's own parameter or `Self.T` (16c)."""
    for v in (binding or {}).values():
        if not isinstance(v, str):
            continue
        vs = v.strip()
        if vs in enclosing_tparams:
            return False
        if vs.startswith("Self."):
            return False
    return True


def _call_has_unknown_keyword(call, tmpl, kind) -> bool:
    """Unknown keyword -> not inferable (16c)."""
    kws = getattr(call, "kwargs", None) or []
    if not kws:
        return False
    if kind != KIND_FN or not tmpl:
        return True
    try:
        from fire_compiler import Parser, py_tokenize
        fn = next((s for s in Parser(py_tokenize(tmpl)).parse_module()
                   if isinstance(s, F.FunctionDef)), None)
        if fn is None:
            return True
        names = set()
        for p in (getattr(fn, "params", None) or []):
            if isinstance(p, (list, tuple)) and p:
                n = p[0]
                if isinstance(n, str):
                    names.add(n.lstrip('*'))
        for kw in kws:
            kname = kw[0] if isinstance(kw, (list, tuple)) else kw
            if kname not in names:
                return True
        return False
    except Exception:
        return True


def _effective_fn_args(call, fparams):
    """Positional args by position, keyword args by parameter name (16c)."""
    def _pname(p):
        return p[0] if isinstance(p, (list, tuple)) and p else p
    name_to_idx = {}
    for i, p in enumerate(fparams):
        pn = _pname(p)
        if isinstance(pn, str):
            name_to_idx[pn.lstrip('*')] = i
    eff = [None] * len(fparams)
    for i, arg in enumerate(getattr(call, "args", None) or []):
        if i < len(eff):
            eff[i] = arg
    for kw in (getattr(call, "kwargs", None) or []):
        try:
            kname, karg = (kw[0], kw[1]) if isinstance(kw, (list, tuple)) else (None, None)
        except Exception:
            continue
        if kname in name_to_idx:
            idx = name_to_idx[kname]
            if idx < len(eff):
                eff[idx] = karg
    return eff


def _bind_from_annotations(call, declared, tmpl, params) -> dict:
    """Keyword-aware binding of template params from argument annotations and
    type-spelled defaults (16c).  Comptime-value defaults do NOT settle a param.
    """
    import elaborate
    from fire_compiler import Parser, py_tokenize
    binding: dict = {}
    fn = next((s for s in Parser(py_tokenize(tmpl)).parse_module()
               if isinstance(s, F.FunctionDef)), None)
    if fn is not None:
        fparams = getattr(fn, "params", None) or []
        eff = _effective_fn_args(call, fparams)
        for i, arg in enumerate(eff):
            if arg is None or i >= len(fparams):
                continue
            pentry = fparams[i]
            pann = pentry[1] if isinstance(pentry, (list, tuple)) and len(pentry) > 1 else None
            if not isinstance(pann, str) or not isinstance(arg, F.IdentExpr):
                continue
            arg_ann = declared.get(arg.name)
            if not isinstance(arg_ann, str) or not arg_ann.strip():
                continue
            arg_ann = arg_ann.strip()
            pann_s = pann.strip()
            if pann_s.startswith('Self.'):
                pann_s = pann_s[5:]
            if pann_s in params:
                binding[pann_s] = arg_ann
                continue
            m = _SIMD_PARAM_RE.match(pann_s)
            if m:
                tp = m.group(1).strip()
                if tp in params:
                    binding[tp] = arg_ann
                    if m.group(2) and m.group(2).strip() in params:
                        binding[m.group(2).strip()] = '1'
                    continue
            for tp in params:
                if re.search(r'\b' + re.escape(tp) + r'\b', pann_s):
                    binding[tp] = arg_ann
                    break
    defaults = elaborate.type_param_defaults(tmpl)
    for p in params:
        if p not in binding:
            dtext = defaults.get(p, '')
            if not dtext or not str(dtext).strip():
                continue
            dtext_s = str(dtext).strip()
            if _default_text_is_type_spelling(dtext_s):
                d = elaborate._default_type_arg(dtext_s)
                if d is not None:
                    binding[p] = d
            # else comptime-value default: leave unset (16c)
    return binding

def infer_bare_call(consumer_stmts, enclosing_stmt, call, template_src, kind, module_level_values=None, consumer_src=None):
    """Concrete type-argument tuple for a BARE call, or None (16b/16c).
    16c: kwargs matched by name (unknown -> None), type-spelled defaults may
    settle uninferred params, comptime-value defaults refuse, result that is
    the enclosing template's own parameter or Self.T -> None.
    """
    import elaborate
    func = getattr(call, "func", None)
    if not isinstance(func, F.IdentExpr):
        return None
    if _call_has_unknown_keyword(call, template_src, kind):
        return None
    declared = _declared_types_in_scope(consumer_stmts, enclosing_stmt)
    arg_ctypes, has_literal = _bare_call_arg_annotations(call, declared, declared)
    enclosing_tparams = _enclosing_template_params(consumer_stmts, enclosing_stmt, consumer_src)

    if kind == KIND_FN:
        if not template_src:
            return None
        params = elaborate.type_param_names(template_src)
        if not params:
            return None
        has_kwargs = bool(getattr(call, "kwargs", None) or [])
        defaults = elaborate.type_param_defaults(template_src)
        has_comptime_default = any(
            d and str(d).strip() and not _default_text_is_type_spelling(str(d))
            for d in defaults.values())
        # Skip fast path when arg annotations are caller's own template params
        # (defect #3) or Self.T - elaborate.infer_type_args can mis-map them.
        risky_ann = any(
            isinstance(a, str) and (a.strip() in enclosing_tparams or a.strip().startswith('Self.'))
            for a in arg_ctypes if a)
        if not has_kwargs and not has_literal and not has_comptime_default and not risky_ann:
            inferred = elaborate.infer_type_args(template_src, arg_ctypes)
            if inferred and _inferred_binding_ok(dict(zip(params, inferred)), enclosing_tparams):
                return tuple(inferred)
        binding = _bind_from_annotations(call, declared, template_src, params)
        if all(p in binding for p in params):
            if not _inferred_binding_ok(binding, enclosing_tparams):
                return None
            return tuple(binding[p] for p in params)
        return None
    if kind == KIND_STRUCT:
        if has_literal or getattr(call, "kwargs", None):
            return None
        module_src = getattr(call, '_module_src', None)
        if module_src is None:
            module_src = template_src if isinstance(template_src, str) else ''
        inferred = elaborate.infer_struct_type_args(module_src, func.name, arg_ctypes)
        if inferred and _inferred_binding_ok({str(i): v for i, v in enumerate(inferred)}, enclosing_tparams):
            return tuple(inferred)
        return None
    return None


def _bare_call_demand(module_src, base, stmts, enclosing_stmt, call, module_level,
                      *, tolerate_unreadable, consumer_src=None):
    """The validated type-argument tuple for the bare call `call` to `base`, a
    template of `module_src`, or `None`.

    Shared tail of the two entries to `infer_bare_call`.  `instantiate` is asked
    whether the inferred arguments are admitted (its result is discarded; its
    `MonomorphError` is the point).  `tolerate_unreadable` is the imported-module
    entry's policy: a name whose template neither extractor can read is skipped,
    where the consumer-module entry lets the refusal stand (`template_kind`) or
    infers against no template text (`_template_source`).
    """
    try:
        kind = template_kind(module_src, base)
    except MonomorphError:
        if tolerate_unreadable:
            return None
        raise
    try:
        tmpl = _template_source(module_src, base, kind)
    except MonomorphError:
        if tolerate_unreadable:
            return None
        tmpl = None
    call._module_src = module_src
    inferred = infer_bare_call(stmts, enclosing_stmt, call, tmpl, kind, module_level, consumer_src)
    if not inferred:
        return None
    instantiate(module_src, base, tuple(inferred))
    return tuple(inferred)


def annotated_construction_demands(stmts, templates=None, skip=()) -> list:
    """`[(base, (type arg, …), call), …]` for `x: Base[…] = Base(…)`.

    A type argument WRITTEN IN A NON-CALL POSITION is not a demand to
    `all_instantiation_calls`, which walks CALL sites: `VarDecl.type_ann` is a
    STRING by the time an AST carries it (`x: Base[Int]`), not a subscript node,
    so the bracket in it is invisible to every reader built on the parsed tree.
    The construction on the right is a bare `Base(...)`, and because the
    template's own body was dropped by `without_template_bodies` it names no
    struct and no function — the binding loses its home and the field read is
    refused, or the image carries a call nothing provides.  This is the reader
    that turns the ANNOTATION into a demand, so the machinery that already
    handles an explicit-bracket call (`instantiate_all` +
    `rewrite_instantiation_calls`) handles this spelling too.

    `templates`, when given, is the set of names this is allowed to speak for
    (a module's own STRUCT templates); `None` asks about every annotation and
    lets the caller's `demap` decide, which is what the rewrite pass wants.

    `skip` is the module's own GENERIC TEMPLATE names, and it is load-bearing
    rather than tidy: a demand reader runs before `without_template_bodies`
    drops the template declarations, and an annotated construction inside one
    (`struct Outer[T]: … var x: Inner[T] = Inner()`) would otherwise demand
    `Inner` at the outer template's PARAMETER, publishing `Inner_T` with `T`
    undeclared.  A template's own body is in no image, so it states no demand.

    The argument spellings are checked twice and both are the safe direction:
    each must be a bare or dotted identifier (a nested application is left out
    rather than mangled by a second rule), and it must not be a name the reading
    SCOPE binds as a value — the same "a name nothing binds is a type" rule
    `type_arg_text` states, because an annotation that names a local is not a
    type no matter where the parser put it.
    """
    from formal import model as M                  # lazy — cycle
    from formal.build import _names_bound_in       # lazy — cycle

    skip = set(skip or ())
    out = []
    module_values = set(M.collect_module_symbols(stmts) or {})
    for st in stmts:
        if getattr(st, "name", None) in skip:
            continue
        values = _names_bound_in(st) if isinstance(st, F.FunctionDef) \
            else module_values
        for node in M.iter_nodes(st):
            if not isinstance(node, F.VarDecl):
                continue
            ann = node.type_ann
            value = node.value
            if not isinstance(ann, str) or not isinstance(value, F.CallExpr):
                continue
            if not isinstance(value.func, F.IdentExpr):
                continue
            base = M.annotation_base_name(ann)
            if base is None or value.func.name != base:
                continue
            if templates is not None and base not in templates:
                continue
            texts = M._split_type_args(ann)
            if not texts:
                continue
            if any(t in values or not _ANNOTATION_TYPE_ARG_RE.match(t)
                   for t in texts):
                continue
            out.append((base, tuple(texts), value))
    return out


def own_annotation_demands(src: str, stmts) -> dict:
    """`{template: [(type arg, …), …]}` — the annotated constructions of `src`'s
    OWN struct templates.

    The own-template half of `annotated_construction_demands`, and a function
    rather than a clause in each of its two callers because both the executable
    path (`formal/imports.py::_own_instantiations`) and the library path
    (`build_module_dylib`, whose own demand set feeds BOTH the artifact's
    identity and the call-site rewrite) need the same table from the same rule.
    A name the export rule filed as a template that neither extractor can pull
    out is skipped rather than fatal — `template_names`' own documented
    imprecision — because this is a demand and not the place to report it.
    """
    structs = set()
    for name in template_names(src):
        try:
            if template_kind(src, name) == KIND_STRUCT:
                structs.add(name)
        except MonomorphError:
            continue
    out: dict = {}
    for base, args, _call in annotated_construction_demands(
            stmts, structs, skip=template_names(src)):
        entries = out.setdefault(base, [])
        if args not in entries:
            entries.append(args)
    return out


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


def value_demands_for(consumer_src: str, module_src: str, templates,
                      own=()) -> dict:
    """`{template: [(arg, …), …]}` — the brackets `demands` DROPPED that a
    declaration in `module_src` admits as a comptime-VALUE instantiation.

    `all_bracketed_calls`'s permissive set minus what `demands` already found,
    filtered by asking the declaration itself: `instantiate(module_src, name,
    args)` is called and a `MonomorphError` means the arguments are not an
    instantiation of the template `module_src` declares, so nothing is added.
    That admission test is where the two pinned non-demands stay non-demands:

      * `Pair[2]` — `Pair[T]`'s `T` is a TYPE parameter, and a bare value in a
        type's position is refused by `instantiate`'s kind check;
      * `tile[2, 3]` — `tile` is a FUNCTION template, whose value specialization
        the local machinery already answers, so `instantiate` refuses to
        publish a second boundary symbol for it.

    and where `Tagged[Int, 0]` (a STRUCT with `origin: Int`) is admitted.  The
    check lives here rather than in the walk because only the DECLARATION knows
    a parameter's kind, and this function is the one place a consumer's
    permissive set meets the module that owns the template.

    `module_src` is the DECLARING module's source, so a caller that already has
    it (the own-template path) passes it and one that does not reads it once
    (`formal/imports.py::instantiation_demands`, only when a candidate exists).
    """
    wanted = {n for n in (templates or ()) if n} - {n for n in (own or ()) if n}
    if not wanted:
        return {}
    strict = all_instantiation_calls(consumer_src)
    loose = all_bracketed_calls(consumer_src)
    out: dict = {}
    for name in sorted(wanted):
        already = set(strict.get(name, ()))
        for args in loose.get(name, ()):
            if args in already:
                continue
            try:
                instantiate(module_src, name, args)
            except MonomorphError:
                continue
            out.setdefault(name, []).append(args)
    return out


def own_demands(module_src: str) -> dict:
    """`{template: [(type arg, …), …]}` — what `module_src` asks of the
    templates `module_src` ITSELF declares.

    `own=()` is the whole of it, and it is `demands`' own parameter rather than
    a separate rule: `demands` skips the consumer's own templates because a
    call to a generic this unit compiles is answered by the local-specialisation
    machinery (`_specialization_of` → `comptime.specialization_name`), and that
    is true of a FUNCTION template (`def twice[T]` beside `twice[Int](n)`) and
    FALSE of a STRUCT template, whose instantiation is emitted under a mangled
    name nothing had emitted. So the own set is empty for the caller that wants
    it skipped and this function for the two that want it asked
    (`formal/imports.py::_own_instantiations` for an executable,
    `build_module_dylib` for a library), and there is one definition of the set
    rather than a rule in each.

    The COMPTIME-VALUE half is `value_demands_for`'s, and it is merged here
    rather than left to the caller because this is the module's OWN source: the
    declaration `Tagged[T, origin: Int]` and the call `Tagged[Int, 0]()` are in
    one text, so the admission test needs no source read and no attribution.

    Measured, one file, both architectures, a struct template applied beside its
    own declaration:

        struct Pair[T]:
            var first: T
        def make() -> Int:
            var a = Pair[Int]()
            a.first = 7
            return a.first
        #   executable: builds and answers 7
        #   LIBRARY:   refused — "`Pair` calls a name this unit does not
        #              compile … so a call arriving here asked for none"

    The library half is `build_module_dylib`'s, and it needs this set in two
    places — the artifact's identity (`demands_key`, so two libraries for the
    same source and different own instantiations cannot share a path) and the
    rewrite of this module's own call sites — which is why it is a function and
    not a line in one of them.
    """
    names = template_names(module_src)
    want = demands(module_src, names, own=())
    for name, args in value_demands_for(module_src, module_src, names).items():
        want.setdefault(name, [])
        for a in args:
            if a not in want[name]:
                want[name].append(a)
    # Collect variadic calls in own module
    try:
        from formal.build import parse_module
        import fire_compiler as F
        from formal import model as M
        stmts = parse_module(module_src)
        # Find variadic functions in this module
        variadics = {}
        for st in stmts:
            if isinstance(st, F.FunctionDef):
                fixed = 0
                var_name = None
                for pentry in getattr(st, 'params', []) or []:
                    if isinstance(pentry, (list, tuple)) and pentry:
                        pname = pentry[0]
                        if isinstance(pname, str):
                            if pname.startswith('**'):
                                break
                            elif pname.startswith('*') and not pname.startswith('**'):
                                var_name = pname[1:] or pname
                                break
                            else:
                                fixed += 1
                if var_name is not None and st.name in names:
                    variadics[st.name] = fixed
        if variadics:
            for st in stmts:
                for node in M.iter_nodes(st):
                    if isinstance(node, F.CallExpr):
                        func = getattr(node, 'func', None)
                        if isinstance(func, F.IdentExpr):
                            bname = func.name
                            if bname in variadics:
                                nargs = len(getattr(node, 'args', None) or [])
                                fixed = variadics[bname]
                                extras = nargs - fixed
                                if extras >= 0:
                                    arity_args = (f'__variadic_{extras}_{fixed}__',)
                                    want.setdefault(bname, [])
                                    if arity_args not in want[bname]:
                                        want[bname].append(arity_args)
    except Exception:
        pass
    return want


def demap_from(made) -> dict:
    """`{(base, (type arg, …)): mangled}` from `instantiate_all`'s FIRST list.

    The one reader of that tuple shape into a rewrite table, because the shape
    carries `base` and `args` — the spelling the CALL SITE used — and recovering
    either from the mangled name would be a second mangling rule to keep in step
    with `monomorphize.mangle`.  Both callers need the same table and both get
    it from the `made` they already have, so neither re-derives a name.
    """
    return {(base, tuple(args)): mangled for base, mangled, args, _p in made}


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


def instantiate_all(module_src: str, wanted: dict,
                    record: bool = False) -> tuple:
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

    `record` publishes the failures in `_FAILED_DEMANDS`, and only the UNIT's own
    half passes it (`formal/imports.py::_own_instantiations`).
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
    if record:
        _record_failed_demands(failed)
    return made, failed


def instantiations_by_base(demap: dict) -> dict:
    """`{base name: {mangled name, …}}` — the instantiations `demap` holds for
    each template, which is what "how many instantiations does this unit apply
    of THAT template" is.

    One reader for both arms of the class-attribute rule
    (`rewrite_instantiation_uses`): a read named `Template.<attr>` carries no
    bracket and so names no instantiation of its own, which makes the COUNT the
    whole of the answer — one instantiation and the read has exactly one
    instantiation it could mean, two or more and it names none of them in
    particular. Keyed by the demap rather than recomputed from the source,
    because the demap is the table the declarations came out of and a count taken
    anywhere else is a second answer to "what was instantiated" that can disagree
    with the ones on the link line."""
    out: dict = {}
    for (base, _args), mangled in demap.items():
        out.setdefault(base, set()).add(mangled)
    return out


def rewrite_instantiation_uses(stmts, demap: dict) -> int:
    """Rewrite every USE of a generic template to the mangled instantiation, in
    place: `Base[Args](…)` and `Base.<attr>` alike."""
    from formal import model as M                  # lazy — cycle
    from formal.build import _names_bound_in       # lazy — cycle
    uniq = _unique_instantiation(demap)
    by_base = instantiations_by_base(demap)
    # The demand was recorded under the DEFINING name (see
    # `local_defining_names`), so a call site's own spelling has to be mapped
    # through the same table before it can name that demand's table entry.
    defining = local_defining_names(stmts)
    n = 0
    # The ANNOTATION half
    for base, args, call in annotated_construction_demands(stmts):
        mangled = demap.get((base, args))
        if mangled is None:
            continue
        call.func = F.IdentExpr(name=mangled,
                                line=getattr(call.func, "line", 0),
                                col=getattr(call.func, "col", 0))
        n += 1
    for st in stmts:
        if isinstance(st, F.FunctionDef):
            values = _names_bound_in(st)
            shadowed = values
        else:
            syms = M.collect_module_symbols(stmts) or {}
            values = set(syms)
            shadowed = _shadowed_here(syms)
        for node in M.iter_nodes(st):
            if isinstance(node, F.MemberExpr) \
                    and isinstance(node.obj, F.IdentExpr):
                if node.obj.name in shadowed:
                    continue
                base_name = defining.get(node.obj.name, node.obj.name)
                mangled = uniq.get(base_name)
                if mangled is None:
                    # TWO OR MORE instantiations: the read names none of them in
                    # particular, and both ways of proceeding are wrong (the
                    # template's own unsubstituted alias is a number no
                    # instantiation stands behind; the first one built is an
                    # order the source does not state) — so refuse, by name.
                    # ZERO instantiations is left alone: the class-attribute
                    # refusal already in `formal/build.py` is true of it.
                    made = by_base.get(base_name) or ()
                    if len(made) > 1 and node.member:
                        raise M.CodegenError(M.template_attribute_read_ambiguous(
                            base_name, node.member, sorted(made)))
                    continue
                node.obj = F.IdentExpr(name=mangled, line=node.obj.line,
                                       col=node.obj.col)
                n += 1
                continue
            if not isinstance(node, F.CallExpr):
                continue
            base = _callee_base(node)
            if base is not None:
                base = defining.get(base, base)
                args = tuple(_bracket_all_args(node.func, values))
                mangled = demap.get((base, args))
                if mangled is None:
                    continue
                node.func = F.IdentExpr(name=mangled,
                                        line=getattr(node.func.obj, "line", 0),
                                        col=getattr(node.func.obj, "col", 0))
                n += 1
                continue
            # Try bare call
            func = getattr(node, "func", None)
            if isinstance(func, F.IdentExpr):
                bname = func.name
                if bname in shadowed:
                    continue
                # If there's exactly one instantiation for this base in demap, use it
                candidates = [(k[1], v) for k, v in demap.items() if k[0] == bname]
                if len(candidates) == 1:
                    _args_cand, mangled = candidates[0]
                    node.func = F.IdentExpr(name=mangled,
                                            line=getattr(func, "line", 0),
                                            col=getattr(func, "col", 0))
                    n += 1
                    continue
                # Or if there's any entry, try to match
                if candidates:
                    nargs = len(getattr(node, "args", None) or [])
                    # Try to find variadic match
                    for _args_cand, mangled in candidates:
                        try:
                            if _args_cand and len(_args_cand) == 1:
                                s = str(_args_cand[0])
                                if s.startswith('__variadic_') and s.endswith('__'):
                                    inner = s[len('__variadic_'):-len('__')]
                                    if '_' in inner:
                                        extras_s, fixed_s = inner.split('_')
                                        fixed_c = int(fixed_s)
                                        extras_c = int(extras_s)
                                        if fixed_c + extras_c == nargs:
                                            node.func = F.IdentExpr(name=mangled,
                                                                    line=getattr(func, "line", 0),
                                                                    col=getattr(func, "col", 0))
                                            n += 1
                                            break
                                    else:
                                        extras_c = int(inner)
                                        # try to match if extras_c == nargs - something
                                        # or just use it
                                        node.func = F.IdentExpr(name=mangled,
                                                                line=getattr(func, "line", 0),
                                                                col=getattr(func, "col", 0))
                                        n += 1
                                        break
                        except Exception:
                            continue
                    else:
                        # Try to pick the first one if unambiguous
                        _args_cand, mangled = candidates[0]
                        node.func = F.IdentExpr(name=mangled,
                                                line=getattr(func, "line", 0),
                                                col=getattr(func, "col", 0))
                        n += 1
                        continue
                    continue
    return n


def _unique_instantiation(demap: dict) -> dict:
    """`{base: mangled}` for the bases `demap` holds EXACTLY ONE
    instantiation of — the bases a bare `Base.<member>` read can be answered
    from.

    The filter is the whole of the rule and it is a filter rather than a choice:
    `demap` is keyed `(base, args)` and holds every argument spelling the
    consumer wrote, so a base with two entries is a question with two answers and
    a base with none is a question this build never instantiated.  Both are left
    out, and the read that needed them keeps the refusal it has today.
    """
    counts: dict = {}
    for base, _args in demap:
        counts[base] = counts.get(base, 0) + 1
    return {base: mangled for (base, _args), mangled in demap.items()
            if counts.get(base) == 1}


def _shadowed_here(syms: dict) -> set:
    """The module-level names bound to a VALUE here, `imported` ones excluded.

    `collect_module_symbols` is about what a module PROVIDES, and one of its
    four sites is an import — `from sizelib import TypeDict` reports `TypeDict`.
    A local-shadow check has to see through that, because `TypeDict.length` read
    straight after that import is the spelling the rewrite exists for, and using
    the whole set would leave it unrewritten at module level while rewriting it
    inside a function: one construct with two answers depending on where it is
    written.  The three remaining sites (`assigned`, `rebound`, `declared`) are
    all bindings, which is what a shadow is.
    """
    return {n for n, sym in (syms or {}).items()
            if getattr(sym, "site", None) != "imported"}
def _consumer_statements(consumer_src: str) -> list:
    """`consumer_src`'s top-level statements, from ONE parse.

    The parse goes through `formal.build.parse_module`, the same front end both
    dylib and executable builds use, so the nodes here are the ones the rest of
    the pipeline sees — including the `with_filename` that puts line numbers on
    them.  A file this cannot parse raises out of the caller, which is right: a
    consumer whose own parse failed has a more fundamental problem than a demand
    for an instantiation, and swallowing that here would turn a parse error into
    an empty demand set and then into "that module exports nothing".

    **Once per source text**, because there are now two readers of it —
    `all_instantiation_calls` and `_bracketed_callee_bases` — and both are
    questions about the same bytes.  Each answers a different question about the
    SAME walk, and re-parsing a whole file for the second one is exactly the
    cost this module's docstring measures (`py_tokenize_named` was 51 % of a
    stdlib build before its parses were deduplicated).  The stored value is the
    parsed list, which callers only read; the top-level `list()` copy below
    keeps a caller from mutating the shared list's own structure, and the nodes
    are shared exactly as `without_template_bodies`'s docstring says they are.
    """
    from formal.build import parse_module          # lazy — cycle
    return list(_derived_from_source(
        "_consumer_statements", consumer_src,
        lambda: parse_module(consumer_src)))


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


def local_defining_names(stmts) -> dict:
    """`{local spelling: the DEFINING name}` for this unit's imports.

    `from pairlib import Pair as P` binds `P`, and both the DEMAND this unit
    produces for `P[Int]()` and the REWRITE of that call site have to name the
    template by the name its module gave it (`Pair`), because that is the
    export-table key and the key `instantiate_all` looks the declaration up
    under.  Read off the same table the emitters resolve a call site through —
    `formal/imports.py::imported_bindings`, which `formal/build.py`'s
    `_import_aliases` hands to both backends — so the spelling at the call
    site, the demand it produces and the symbol it binds are ONE decision read
    three times rather than three spellings that agree until they do not.

    A local definition wins over an import of the same name
    (`imported_bindings`' own rule), which is the precedence
    `imported_struct_defs` states for the declarations too.  A name with no
    alias is present as itself (`from m import f` reports `f`), so mapping
    through this table is a no-op for every non-aliased spelling, which is
    every case that already lowers.

    A MODULE import is left out, and the filter is the dot rather than a kind
    test: `imported_bindings` reports `import a.b` as `a` bound to the module
    spelling `a.b`, which is a module and not a name anything declares — a
    defining name is always one identifier, so a value with a dot in it is the
    only shape this table must not carry.
    """
    from formal.imports import imported_bindings     # lazy — cycle
    return {local: defining
            for local, (_module, defining)
            in imported_bindings(stmts or ()).items()
            if isinstance(defining, str) and "." not in defining}


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

    **A bare literal is dropped entirely here.**  Literal admission goes through
    the permissive reader (`_bracket_all_args`) plus declaration-aware
    `value_demands_for`/`instantiate` — the strict reader must not see bare
    literals at all.
    """
    items = bracket_items(sub)
    spelled = [type_arg_text(i, values) for i in items]
    if not spelled or any(s == "" for s in spelled):
        return []
    return spelled


def _value_literal_arg_text(expr) -> str:
    """The spelling of a bracket item that is a bare VALUE LITERAL, or "".

    One reader for the mixed-bracket rule `_bracket_type_args` applies, and it
    renders a literal the same way `_display_element_text` does — `repr` for a
    string, the signed text for a `UnaryOp` — because the rendering is both the
    mangled symbol fragment and the text substituted into the body, and the two
    must be the same value the source wrote.  A name, a call, an arithmetic
    expression and a display are all `""` here: a name is already read by
    `type_arg_text`, a display has its own reader, and the rest have no closed
    form to substitute.
    """
    if isinstance(expr, F.IntLiteral):
        return str(expr.value)
    if isinstance(expr, F.FloatLiteral):
        return repr(expr.value)
    if isinstance(expr, F.StringLiteral):
        return repr(expr.value)
    if isinstance(expr, F.BoolLiteral):
        return "True" if expr.value else "False"
    if isinstance(expr, F.NoneLiteral):
        return "None"
    if isinstance(expr, F.UnaryOp) and expr.op in ("-", "+"):
        inner = _value_literal_arg_text(expr.operand)
        return f"{expr.op}{inner}" if inner else ""
    return ""


def _bracket_all_args(sub, values=()) -> list:
    """Like `_bracket_type_args`, but a bare literal is a spelling too.

    The permissive twin `all_bracketed_calls`'s walk reads.  Each item is a
    type spelling when `type_arg_text` gives one (`Int`, `simd.float32`,
    `List_Int`, and a display — whose own text IS its spelling) and otherwise a
    literal via `_display_element_text` (`0`, `-3`, `True`, `"x"`).  A
    computed argument, and a bare identifier the reading scope binds as a
    value, still spell nothing and make the whole bracket a non-candidate —
    that is the property `type_arg_text`'s docstring is built around, and it
    is kept here so the permissive reader differs from the strict one in
    exactly one way.

    It returns the SPELLINGS only, not which of them are values: the value/type
    distinction is a question about the DECLARATION
    (`elaborate.type_param_kinds`), asked by `instantiate`, so the walk that
    cannot see a declaration does not pretend to answer it.
    """
    out = []
    for item in bracket_items(sub):
        text = type_arg_text(item, values) or _display_element_text(item, values)
        if not text:
            return []
        out.append(text)
    return out


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


def _bracketed_callee_bases(consumer_src: str) -> set:
    """Every bare name used as a BRACKETED callee in `consumer_src`.

    `f[a, b](…)` for ANY bracket items — a type list, a value list, a mixed one
    — and dotted bases excluded, because `_callee_base` is the one recogniser
    and it answers None for those.  `all_instantiation_calls` is this same walk
    with the concrete-TYPE-argument filter on top; this is the unfiltered
    question, and `concrete_struct_templates` asks it because a template a call
    site applies with BRACKETS is already answered by the instantiation
    machinery (type items) or by the refusal those brackets earn (value items),
    so keeping the declaration as well would move which code path answers that
    call — measured: `Triple[Int, s, False](5)` on a phantom-parameter template
    stopped producing "a S receiver is stored in a container" and produced the
    tuple-index refusal instead.

    **Read from the SOURCE, not from a build's statement list.** By the time
    `without_template_bodies` runs, `_imported_structs` has already REWRITTEN
    this file's own bracketed instantiation calls to their mangled names, so a
    statement-list walk no longer sees the bracket that earned each demand —
    measured: `Box[Int, [1, 2, 3]]()` was rewritten, its phantom template was
    then kept, and the build refused. The parse is `_consumer_statements`, which
    is memoised and already made for `all_instantiation_calls`.
    """
    from formal import model as M                  # lazy — cycle
    found = set()
    for st in _consumer_statements(consumer_src):
        for node in M.iter_nodes(st):
            if isinstance(node, F.CallExpr):
                base = _callee_base(node)
                if base:
                    found.add(base)
    return found


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


def inferred_demands_for(consumer_src: str, module_src: str, templates,
                         own=()) -> dict:
    """`{template: [(type arg, …), …]}` — bare calls to templates whose type
    arguments can be inferred from argument types. This is the imported-module
    entry to `infer_bare_call`."""
    wanted = {n for n in (templates or ()) if n} - {n for n in (own or ()) if n}
    if not wanted:
        return {}
    from formal import model as M

    out: dict = {}
    stmts = _consumer_statements(consumer_src)

    syms = M.collect_module_symbols(stmts) or {}
    module_level = set()
    for name, sym in syms.items():
        if getattr(sym, "site", None) == "comptime" and getattr(sym, "literal", None) is None:
            continue
        module_level.add(name)

    for st in stmts:
        enclosing = st if isinstance(st, F.FunctionDef) else None
        for node in M.iter_nodes(st):
            if not isinstance(node, F.CallExpr):
                continue
            func = node.func
            if not isinstance(func, F.IdentExpr) or func.name not in wanted:
                continue
            inferred = _bare_call_demand(module_src, func.name, stmts, enclosing,
                                         node, module_level, tolerate_unreadable=True,
                                         consumer_src=consumer_src)
            if inferred:
                out.setdefault(func.name, []).append(inferred)
    # Deduplicate
    result = {}
    for k, v in out.items():
        seen = set()
        res = []
        for a in v:
            if a not in seen:
                res.append(a)
                seen.add(a)
        result[k] = res
    return result


def _rewrite_variadic_node(node, var_name, arity):
    """Rewrite a node in a variadic function body for specialization."""
    try:
        import fire_compiler as F_mod
        F = F_mod
        # Check for len(var_name)
        if isinstance(node, F.CallExpr):
            func = getattr(node, 'func', None)
            if isinstance(func, F.IdentExpr) and func.name == 'len':
                args = getattr(node, 'args', None) or []
                if len(args) == 1 and isinstance(args[0], F.IdentExpr) and args[0].name == var_name:
                    return F.IntLiteral(value=arity, line=getattr(node, 'line', 0), col=getattr(node, 'col', 0))
            # Rewrite inside
            new_node = copy.copy(node)
            new_args = []
            for a in getattr(node, 'args', None) or []:
                new_args.append(_rewrite_variadic_node(a, var_name, arity))
            new_node.args = new_args
            if hasattr(new_node, 'func'):
                new_node.func = _rewrite_variadic_node(new_node.func, var_name, arity)
            return new_node
        if isinstance(node, F.SubscriptExpr):
            obj = getattr(node, 'obj', None)
            if isinstance(obj, F.IdentExpr) and obj.name == var_name:
                idx = getattr(node, 'index', None)
                if isinstance(idx, F.IntLiteral):
                    i = idx.value
                    if 0 <= i < arity:
                        return F.IdentExpr(name=f'{var_name}_{i}', line=getattr(node, 'line', 0), col=getattr(node, 'col', 0))
                    elif arity == 0:  # original function stub case
                        return F.IntLiteral(value=0, line=getattr(node, 'line', 0), col=getattr(node, 'col', 0))
            new_node = copy.copy(node)
            if getattr(node, 'obj') is not None:
                new_node.obj = _rewrite_variadic_node(node.obj, var_name, arity)
            if getattr(node, 'index') is not None:
                new_node.index = _rewrite_variadic_node(node.index, var_name, arity)
            return new_node
        if isinstance(node, F.IdentExpr):
            return node
        if isinstance(node, F.ReturnStmt):
            new_node = copy.copy(node)
            if getattr(node, 'value') is not None:
                new_node.value = _rewrite_variadic_node(node.value, var_name, arity)
            return new_node
        if isinstance(node, F.AssignStmt):
            new_node = copy.copy(node)
            if getattr(node, 'value') is not None:
                new_node.value = _rewrite_variadic_node(node.value, var_name, arity)
            if getattr(node, 'target') is not None:
                new_node.target = _rewrite_variadic_node(node.target, var_name, arity)
            return new_node
        if isinstance(node, F.ExprStmt):
            new_node = copy.copy(node)
            if getattr(node, 'expr') is not None:
                new_node.expr = _rewrite_variadic_node(node.expr, var_name, arity)
            return new_node
        if isinstance(node, F.IfStmt):
            try:
                new_node = copy.copy(node)
                if getattr(node, 'condition') is not None:
                    try:
                        new_node.condition = _rewrite_variadic_node(node.condition, var_name, arity)
                    except Exception:
                        pass
                elif getattr(node, 'test') is not None:
                    try:
                        new_node.test = _rewrite_variadic_node(node.test, var_name, arity)
                    except Exception:
                        pass
                try:
                    if hasattr(new_node, 'then_body'):
                        new_node.then_body = [_rewrite_variadic_node(n, var_name, arity) for n in (getattr(new_node, 'then_body') or [])]
                    elif hasattr(new_node, 'body'):
                        new_node.body = [_rewrite_variadic_node(n, var_name, arity) for n in (getattr(new_node, 'body') or [])]
                except Exception:
                    pass
                try:
                    if getattr(node, 'else_body') not in (None, []):
                        else_b = getattr(node, 'else_body')
                        if isinstance(else_b, list):
                            new_node.else_body = [_rewrite_variadic_node(n, var_name, arity) for n in else_b]
                        else:
                            new_node.else_body = else_b
                    elif getattr(new_node, 'orelse') not in (None, []):
                        orelse = getattr(new_node, 'orelse')
                        if isinstance(orelse, list):
                            new_node.orelse = [_rewrite_variadic_node(n, var_name, arity) for n in orelse]
                except Exception:
                    pass
                # elifs
                try:
                    elifs = getattr(new_node, 'elifs', None)
                    if elifs:
                        new_elifs = []
                        for e in elifs:
                            if isinstance(e, tuple) and len(e) >= 2:
                                try:
                                    cond_e = _rewrite_variadic_node(e[0], var_name, arity) if hasattr(e[0], '__class__') and not isinstance(e[0], (str,)) else e[0]
                                except Exception:
                                    cond_e = e[0]
                                try:
                                    body_e = [_rewrite_variadic_node(x, var_name, arity) if hasattr(x, '__class__') and not isinstance(x, (str,)) else x for x in e[1]]
                                except Exception:
                                    body_e = e[1]
                                new_elifs.append((cond_e, body_e, *e[2:]))
                            else:
                                new_elifs.append(e)
                        new_node.elifs = new_elifs
                except Exception:
                    pass
                return new_node
            except Exception:
                return node
        try:
            new_node = copy.copy(node)
            for attr in ['value', 'test', 'cond', 'expr', 'operand', 'left', 'right', 'iterable', 'target', 'iter']:
                if hasattr(new_node, attr):
                    val = getattr(new_node, attr)
                    if val is not None and hasattr(val, '__class__') and not isinstance(val, (str, int, float, bool)):
                        try:
                            setattr(new_node, attr, _rewrite_variadic_node(val, var_name, arity))
                        except Exception:
                            pass
            for attr in ['body', 'orelse', 'stmts', 'finally_body']:
                if hasattr(new_node, attr):
                    val = getattr(new_node, attr)
                    if isinstance(val, list):
                        try:
                            setattr(new_node, attr, [_rewrite_variadic_node(v, var_name, arity) if hasattr(v, '__class__') and not isinstance(v, (str,)) else v for v in val])
                        except Exception:
                            pass
            # Also handle elifs etc if they exist
            if hasattr(new_node, 'elifs') and new_node.elifs:
                try:
                    new_elifs = []
                    for e in new_node.elifs:
                        if isinstance(e, tuple) and len(e) >= 2:
                            new_elifs.append((e[0], [_rewrite_variadic_node(x, var_name, arity) if hasattr(x, '__class__') and not isinstance(x, (str,)) else x for x in e[1]], *e[2:]))
                        else:
                            new_elifs.append(e)
                    new_node.elifs = new_elifs
                except Exception:
                    pass
            return new_node
        except Exception:
            return node
    except Exception:
        return node


def _render_function(fn):
    """Render a FunctionDef back to source code (simple renderer)."""
    try:
        # Try to use a simple string representation
        params = []
        for p in getattr(fn, 'params', []) or []:
            if isinstance(p, (list, tuple)):
                if len(p) == 2 and p[1] is not None:
                    params.append(f"{p[0]}: {p[1]}")
                elif len(p) == 2 and p[1] is None:
                    params.append(p[0])
                elif len(p) == 1:
                    params.append(p[0])
                else:
                    params.append(str(p[0]))
            else:
                params.append(str(p))
        params_str = ', '.join(params)
        ret = ''
        rt = getattr(fn, 'return_type', None)
        if rt is not None:
            ret = f' -> {rt}'
        out = []
        out.append(f"def {fn.name}({params_str}){ret}:")
        for stmt in getattr(fn, 'body', []) or []:
            out.append(_render_stmt(stmt, 1))
        return '\n'.join(out) + '\n'
    except Exception as e:
        # Fallback: try to reconstruct from template
        return f"def {fn.name}():\n    pass\n"


def _render_stmt(stmt, indent=0):
    try:
        sp = '    ' * indent
        import fire_compiler as F
        if isinstance(stmt, F.ReturnStmt):
            if getattr(stmt, 'value') is None:
                return sp + 'return'
            return sp + f'return {_render_expr(stmt.value)}'
        if isinstance(stmt, F.ExprStmt):
            return sp + _render_expr(getattr(stmt, 'expr'))
        if isinstance(stmt, F.AssignStmt):
            target = _render_expr(getattr(stmt, 'target'))
            value = _render_expr(getattr(stmt, 'value'))
            return sp + f'{target} = {value}'
        if isinstance(stmt, F.IfStmt):
            test = _render_expr(getattr(stmt, 'test'))
            lines = [sp + f'if {test}:']
            for s in getattr(stmt, 'body') or []:
                lines.append(_render_stmt(s, indent+1))
            if getattr(stmt, 'orelse'):
                lines.append(sp + 'else:')
                for s in stmt.orelse:
                    lines.append(_render_stmt(s, indent+1))
            return '\n'.join(lines)
        # default
        return sp + 'pass'
    except Exception:
        return '    ' * indent + 'pass'


def _render_expr(expr):
    try:
        import fire_compiler as F
        if expr is None:
            return 'None'
        # Try to match by class name too
        clsname = type(expr).__name__
        if isinstance(expr, F.IdentExpr) or clsname == 'IdentExpr':
            return getattr(expr, 'name')
        if isinstance(expr, F.IntLiteral) or clsname == 'IntLiteral':
            return str(getattr(expr, 'value'))
        if isinstance(expr, F.StringLiteral) or clsname == 'StringLiteral':
            return repr(getattr(expr, 'value'))
        if isinstance(expr, F.BoolLiteral) or clsname == 'BoolLiteral':
            return 'True' if getattr(expr, 'value') else 'False'
        if isinstance(expr, F.FloatLiteral) or clsname == 'FloatLiteral':
            return str(getattr(expr, 'value'))
        if isinstance(expr, F.CallExpr) or clsname == 'CallExpr':
            func = _render_expr(getattr(expr, 'func'))
            args = ', '.join(_render_expr(a) for a in (getattr(expr, 'args') or []))
            return f'{func}({args})'
        if isinstance(expr, F.SubscriptExpr) or clsname == 'SubscriptExpr':
            obj = _render_expr(getattr(expr, 'obj'))
            idx = _render_expr(getattr(expr, 'index'))
            return f'{obj}[{idx}]'
        if isinstance(expr, F.BinaryOp) or clsname == 'BinaryOp' or isinstance(expr, getattr(F, 'BinOp', None)) or clsname == 'BinOp':
            left = _render_expr(getattr(expr, 'left'))
            right = _render_expr(getattr(expr, 'right'))
            op = getattr(expr, 'op', '+')
            return f'{left} {op} {right}'
        if isinstance(expr, getattr(F, 'UnaryOp', None)) or clsname == 'UnaryOp':
            op = getattr(expr, 'op', '-')
            operand = _render_expr(getattr(expr, 'operand'))
            return f'{op}{operand}'
        return str(expr)
    except Exception:
        return str(expr)