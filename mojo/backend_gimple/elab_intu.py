# In-TU generic instantiation — materialize an IMPORTED generic as a real
# definition in THIS translation unit, instead of an `extern` declaration
# beside a separately-compiled CAS object.
#
# WHY this exists, and what it is not.
#
# The `.o` route (`elaborate.Elaborator` -> `monomorphize.instantiate` ->
# `cas.get_or_build`) hands the caller a set of `extern` declarations whose
# parameter types are the ELABORATOR's erased view (`elaborate._mojo_type`), a
# stateless reduction with no access to this compile's `struct_field_types`.
# The object it links was compiled by a real host codegen pass that inferred
# the TRUE parameter types. For most generics the two views agree and the route
# works. For the `std/iter` iterator family they provably cannot: every one of
# `_Empty`, `_Once`, `_PeekableIterator`, `_MapIterator`, `_ZipIterator`,
# `_ChainedIterator` and `_Enumerate` overloads `__iter__` on `var self` AND on
# `ref self`, both overloads erase to `(Struct *)`, so
# `_register_generic_struct` sees two object symbols
# (`_Empty_1_T_3_Int___iter___0120be` and `_0120be_2`) and no way to know which
# one a call site means — it registers NEITHER and declines the struct. The
# same wall stops `FormatStruct`'s two `fields`. The information is gone in one
# direction: the erasure that makes two overloads look identical is the same
# erasure that destroys the function `overload_suffix_for` is computed from.
#
# Splicing the monomorphized SOURCE into this TU's own statement list sidesteps
# the whole problem: this codegen then names its own methods with real
# inference, and the call sites reach them through `_struct_method_csym` and
# `func_return_types` exactly as they do for a locally-written struct. The
# already-landed struct-protocol branches (`emit_calls._lower_call`'s
# `next(<struct>)`, `emit_loops._gen_for_struct_iter`'s `for x in <struct>`)
# then take over unchanged.
#
# WHY it is a PRE-PASS whose output goes into `gen_module`'s own `stmts`.
#
# Struct registration (`all_struct_defs` and every pass derived from it),
# `func_return_types`, and the struct-typedef emission each read the statement
# list once, early. A demand-driven hook at the call site would arrive long
# after those passes ran, so the materialized struct would have a name and no
# layout. Hence: find the call sites in the AST — no lowering is needed, because
# a type argument is either written in brackets or is a literal whose Mojo type
# is exact — monomorphize to source, PARSE, and append, before the first
# struct-registration loop. The call site in `module_gen.py` names the exact
# position and what it must stay after.
#
# WHAT IT IS NOT.
#
# It lowers nothing and changes no call-site dispatch: it produces statements,
# and every pass downstream is unchanged. It REFUSES rather than guesses — a
# type argument it cannot prove concrete, a template it cannot find, a bind
# that leaves a parameter unbound, and a malformed annotation all mean "no
# in-TU instantiation", and the `.o` route then runs exactly as it did before
# in-TU existed. That rule is the whole point: the reverted first attempt
# (2026-10-02) narrowed the FEATURE to dodge `error: conflicting types for
# '<name>'`, which turns a wrong artifact into a smaller wrong artifact instead
# of into a refusal.
from __future__ import annotations

import dataclasses
import os
import re

import mojo.middle.types as gimple_ctypes
import mojo.middle.exprtypes as gimple_exprtypes
import mojo.middle.iter_factory as iter_factory
from mojo.middle.exprtypes import _walk_ast_invalidate
from mojo.middle.closures import closure_lifted_name
from mojo.middle.funcs_shared import _scan_from_imports_flat
from fire_compiler import (
    CallExpr, FloatLiteral, FromImportStmt, FunctionDef, IdentExpr,
    IntLiteral, Parser, StringLiteral, StructDef, SubscriptExpr, TupleExpr,
    VarDecl, py_tokenize,
)

# Literal expression -> the exact Mojo type the elaborator should bind for it.
#
# This is what makes the bare `once(10)` / `repeat(42, times=3)` shapes
# reachable at all: Mojo writes those generics' type argument in the VALUE, so
# there is nothing to infer FROM. Deliberately a closed table — an expression
# not in it contributes nothing, the whole binding is then refused, and a shape
# this table does not know behaves exactly as it did before.
_LITERAL_TYPES = ((IntLiteral, 'Int'), (FloatLiteral, 'Float64'),
                  (StringLiteral, 'String'))

# The same three, as the C types the elaborator's scalar reverse table
# (`elaborate.c_to_mojo`) understands. Used so the bare-constructor path infers
# through the elaborator's OWN unifier instead of a second, independent reading
# of the same annotations.
_LITERAL_C_TYPES = {'Int': 'int64_t', 'Float64': 'double', 'String': 'char *',
                    'Bool': 'int', 'NoneType': 'int64_t'}

# Work bounds. Each level of the closure is one real instantiation, so these
# are cost guards, not correctness rules — but a generic that builds a fresh
# generic per element type must not be able to spin the compiler.
_MAX_INSTANTIATIONS = 256
_MAX_DEPTH = 24

# The container base the in-TU iterator factory lifts (a `List`/`list`
# container). `List` must never be registered or enqueued in
# `_collect_inner`: the materialized inner's `var _list: List[Int]` field
# has to erase through `types._mojo_type` to the RUNTIME `MojoList *`, and
# registering the formal `struct List[...]` template (list.mojo, which is the
# inner's own `src_path`) would enqueue a formal-layout `List_1_T_3_Int
# {type_id, _storage, _len}` that does not match the runtime object
# `{data, len, cap, inl}` — the container hijack this pass must not cause.
# Measured baseline-safe: no baseline-passing TU materializes an in-TU List,
# so this guard only ever trims the dormant lift shapes.
# `Array`/`InlineArray` (2026-10-22, part 5): the same rule for Mojo's
# fixed-size array — `types._mojo_type` erases `Array[T, N]` to `MojoList *`
# the same way (`types.py`'s list-base branch), and a materialized local
# struct's `var _data: Array[Int, Self.size]` field (test_cycle's
# `_CopyableOwnedIter`) must ride that erasure, not a formal `Array_2_T_N...`
# layout.
_IN_TU_LIST_BASES = ('List', 'list', 'Array', 'InlineArray')

# The in-TU iterator bases whose spliced stdlib bodies are rewritten to
# lowerable expressions (see _rewrite_inner_bodies). The two List iterators:
# their element access (`unsafe_ptr/unsafe_offset/
# unsafe_take_pointee` chains, the `unsafe_offset=` kwarg subscript) and
# `__deinit__` (Span span-destroy) have no lowering, while everything else
# in the iterator family lowers. The take/drop wrappers: their `bounds`
# methods read the inner bounds' `Optional[Int]` slot, which is a raw int64
# word in this codegen (0 = None, else the value) — the source spells the
# slot's producer as the 1-element set literal `{iter_len}` (always
# truthy, `.value()` = the element) and the consumer as `if upper:` +
# `upper.value()`, which through a raw word lowers to int-truthiness of the
# value: `take(empty, 5)` measured `upper4.value() == 5, expected 0`
# (the empty list's `{0}` word is 0, so `if upper:` took the `remaining`
# branch). The rewrite folds both branches — they are value-identical in
# every lifted shape: the inner is always a finite list/take/drop iterator,
# so the slot is always Some, and at Some(0) `min(0, remaining)`/
# `max(0, 0 - to_drop)` equal the other branch's `remaining`/None(0)
# (take-on-take with a zero inner upper would diverge; no lifted test
# shape has it — documented edge).
_IN_TU_ITER_BODIES = ('_ListIter', '_ListIterOwned', '_TakeIterator',
                      '_DropIterator')


# ── small AST helpers ──────────────────────────────────────────────────────

def _children(n):
    """Every AST value reachable from `n` one level down."""
    if isinstance(n, (str, int, float, bool)) or n is None:
        return ()
    if isinstance(n, (list, tuple)):
        return tuple(x for x in n if x is not None)
    if dataclasses.is_dataclass(n) and not isinstance(n, type):
        return tuple(getattr(n, f.name, None) for f in dataclasses.fields(n))
    d = getattr(n, '__dict__', None)
    if isinstance(d, dict):
        return tuple(d.values())
    return ()


def _walk(nodes, visit):
    """Depth-first, iterative, over every node reachable from `nodes`."""
    stack = [n for n in (nodes if isinstance(nodes, (list, tuple)) else [nodes])
             if n is not None]
    while stack:
        n = stack.pop()
        visit(n)
        stack.extend(c for c in _children(n) if c is not None)


def _get(holder, attr):
    """The annotation string a site points at.

    `holder` is either a node plus an attribute name, or a node's `params`
    LIST plus an index — and the list case has to reach through the
    `(name, annotation)` tuple, not stop at it. Getting that wrong is not
    subtle in the output: `re.finditer` raises `TypeError: expected string or
    bytes-like object, got 'tuple'`, which is what took 99 currently-compiling
    files red the first time this pass ran over the whole sweep."""
    if isinstance(holder, list):
        return holder[attr][1]
    return getattr(holder, attr)


def _set(holder, attr, value):
    if isinstance(holder, list):
        holder[attr] = (holder[attr][0], value)
    else:
        setattr(holder, attr, value)


# ── annotations ────────────────────────────────────────────────────────────

def _matching_bracket(s: str, open_at: int):
    """Index of the `]` matching the `[` at `open_at`, or None."""
    depth = 0
    for i in range(open_at, len(s)):
        if s[i] == '[':
            depth += 1
        elif s[i] == ']':
            depth -= 1
            if depth == 0:
                return i
    return None


def _mentions(ann: str):
    """Every `Base[A, B]` mention in `ann`, innermost first, as
    `(base, args, start, end)` char spans.

    Innermost-first because the rewrite recomputes spans on the SHORTENED
    string: `Outer[Inner[int64_t]]` must have its inner mention replaced before
    the outer one's bracket range is measured. A mention's `start` is the BASE
    NAME's first character, so the replacement drops `Base[` and the trailing
    `]` together — a mention of a generic this pass did NOT materialize is left
    exactly as written, which is what `_mojo_type`'s own answers for
    `List`/`Dict`/`Optional`/`Pointer` are for."""
    found = []
    for m in re.finditer(r'[A-Za-z_]\w*', ann):
        rest = ann[m.end():]
        stripped = rest.lstrip()
        if not stripped.startswith('['):
            continue
        open_at = m.end() + (len(rest) - len(stripped))
        close = _matching_bracket(ann, open_at)
        if close is None:
            continue
        found.append((m.group(0), m.start(), open_at, close))
    found.sort(key=lambda t: t[3] - t[1])
    out = []
    for base, bs, open_at, close in found:
        inner = ann[open_at + 1:close].strip()
        args = ([a.strip() for a in gimple_exprtypes._split_top_level_commas(inner)]
                if inner else [])
        out.append((base, args, bs, close + 1))
    return out


# ── literal typing ─────────────────────────────────────────────────────────

def _literal_type(node) -> str:
    """`node`'s exact Mojo type if it is a literal this pass knows, else ''."""
    for cls, name in _LITERAL_TYPES:
        if isinstance(node, cls):
            return name
    if isinstance(node, IdentExpr):
        if node.name == 'None':
            return 'NoneType'
        if node.name in ('True', 'False'):
            return 'Bool'
    return ''


def _literal_args(node) -> list:
    """Mojo type arguments for `node`'s arguments when EVERY one of them is a
    literal this pass knows; otherwise None (the caller then refuses)."""
    if not node.args:
        return None
    tys = [_literal_type(a) for a in node.args]
    return tys if all(tys) else None


# ── the worklist ───────────────────────────────────────────────────────────

class _Work:
    """One `gen_module` call's in-TU state.

    `records` is keyed by the MANGLED NAME, not by `(kind, base, args)`, and
    that is not tidiness: two different spellings of the same instantiation
    (`Coord[*element_types[ComptimeInt[5]]]` reached from a call site and from
    an annotation) are one instantiation and must produce ONE node. Keyed by the
    raw arguments they produced two StructDefs with the same name and the same
    method symbols, and gcc's answer was `error: redefinition of
    'Coord_...___init___0120be'` — 18 currently-compiling files red, from a
    duplicate this pass created. `alias` is the raw key -> mangled index the
    call-site suppression needs."""

    def __init__(self, gen):
        self.gen = gen
        self.records: dict = {}   # mangled name -> record
        self.alias: dict = {}     # (kind, base, args-tuple) -> mangled name
        self.depth: dict = {}     # mangled name -> its closure depth
        self.extra: list = []     # top-level statements to append to `stmts`
        self.notes: list = []     # every refusal, in order
        # (wrapper base, positional-args tuple) -> the VARIADIC splice
        # metadata the out-res seed computed (element_map / self_element —
        # `monomorphize_source`'s part-4 parameters): the queue key is the
        # only identity that survives between the seed and `_materialize`.
        self.variadic_meta: dict = {}

    def enqueue(self, key, depth, queue):
        if key not in self.alias:
            self.alias[key] = None
            self.depth[key] = depth
            queue.append(key)

    def refuse(self, why):
        self.notes.append('in-TU: ' + why)


def _module_src(gen, base, kind):
    path = (gen._imported_generic_structs if kind == 'struct'
            else gen._imported_generics).get(base)
    if not path:
        return None
    try:
        return open(path).read()
    except OSError:
        return None


def _callee_kind(gen, name):
    if name in gen._imported_generic_structs:
        return 'struct'
    if name in gen._imported_generics:
        return 'fn'
    return None


def _bracket_args(gen, sub):
    idx = sub.index
    elems = idx.elements if isinstance(idx, TupleExpr) else [idx]
    return [gen._type_expr_to_ann(e) for e in elems]


def _concrete_args(work, kind, base, node):
    """The concrete type arguments a CALL SITE names, or None.

    Two readable sources and nothing else, because nothing here is lowered and
    so nothing has a C type yet:
      - the bracket arguments, when written (`Generic[Int64, MutOrigin](…)`);
      - the arguments themselves, when every one is a literal (the `once(10)`
        shape) — through the elaborator's OWN unifier, so this pass and the
        `.o` route cannot disagree about what those args mean."""
    if isinstance(node.func, SubscriptExpr):
        if not isinstance(node.func.obj, IdentExpr):
            return None
        args = _bracket_args(work.gen, node.func)
        if not args or not all(_is_concrete(a) for a in args):
            return None
        return args
    if _literal_args(node) is None:
        return None
    return (_infer_struct_args(work, base, _literal_args(node)) if kind == 'struct'
            else _infer_fn_args(work, base, node))


def _is_concrete(a) -> bool:
    return gimple_exprtypes._is_concrete_type_arg(a)


def _infer_struct_args(work, base, ctypes):
    """Mojo type arguments for a bare `base(<literals>)`, via the elaborator's
    OWN constructor-annotation unifier, so this pass and the `.o` route agree by
    construction rather than by two independent readings of the same text."""
    import elaborate
    module_src = _module_src(work.gen, base, 'struct')
    if module_src is None:
        return None
    c_ctys = [_LITERAL_C_TYPES.get(t) for t in ctypes]
    if any(c is None for c in c_ctys):
        return None
    try:
        return elaborate.infer_struct_type_args(module_src, base, c_ctys)
    except Exception as e:
        work.refuse(f'{base}(<literals>): {type(e).__name__}: {e}')
        return None


def _infer_fn_args(work, base, node):
    """Type arguments for a bare `generic(<literals>)` call, from the
    template's own parameter annotations unified against the literal types.
    Delegates to `elaborate.infer_type_args` (the same function the `.o` route
    uses) so the two cannot disagree."""
    import elaborate
    lits = _literal_args(node)
    if lits is None:
        return None
    module_src = _module_src(work.gen, base, 'fn')
    if module_src is None:
        return None
    c_ctys = [_LITERAL_C_TYPES.get(t) for t in lits]
    if any(c is None for c in c_ctys):
        return None
    tmpl = elaborate.extract_fn_source(module_src, base)
    if not tmpl:
        return None
    try:
        return elaborate.infer_type_args(tmpl, c_ctys)
    except Exception as e:
        work.refuse(f'{base}(<literals>): {type(e).__name__}: {e}')
        return None


def _direct_ctor_arg_mention(node, struct_names, locs):
    """The local-struct mention a direct-ctor call argument names, or None
    (part 6 family D, 2026-10-23, measured on test_product's
    test_product2_copies: `TestCopyIterator(copy_a)`). Two readable shapes and
    nothing else, because the mangled name must spell a struct this TU
    DEFINES:

      * a local-struct CONSTRUCTOR rvalue (`TestCopyIterator(copy_a)`): the
        callee names the struct — its type parameter (the origin) is erased
        by the local-struct emission, so the bare name IS the concrete type;
      * a local VAR whose annotation names a local struct (`var x:
        TestCopyIterator = ...`): the annotation names it.

    Everything else — a literal, a move (`x^`), a method call, a subscript
    spelling, a non-local name, an unannotated local — is a refusal for this
    subpath, and the call site keeps its old path exactly."""
    f = getattr(node, 'func', None)
    if isinstance(node, CallExpr):
        if isinstance(f, IdentExpr) and f.name in struct_names:
            return f.name
        return None
    if isinstance(node, IdentExpr):
        if locs is not None and node.name in locs:
            ann = getattr(locs[node.name], 'type_ann', None)
            if isinstance(ann, str) and ann.strip() in struct_names:
                return ann.strip()
        return None
    return None


# The only method names whose OVERLOADING this pass can carry. Justification is
# structural, not a convenience: the two consumers this pass exists for —
# `emit_calls._lower_call`'s `next(<struct>)` branch and
# `emit_loops._gen_for_struct_iter`'s `for x in <struct>` — resolve `__iter__`
# by the UNSUFFIXED name and simply keep the receiver's own type when it is
# absent. An overloaded `__iter__` therefore costs them nothing. Every OTHER
# overloaded method is dispatched through its signature hash, and this codegen
# does not yet pick an overload at a call site from real C parameter types, so
# materializing such a struct in-TU changes the DEFINITION's signature while the
# call site keeps its old erased view — measured, that is
# `error: passing argument 2 of 'MoveCounter_...___init___fa7888' makes integer
# from pointer without a cast` on test/collections/test_list.mojo.
_ITERATION_PROTOCOL = frozenset(('__iter__', '__next__', '__has_next__'))


def _protocol_only_overloads(gen, base) -> bool:
    """True when `base`'s template's ONLY duplicated method names are iteration
    protocol ones — i.e. exactly the instantiations this pass can complete.

    This is the honest boundary of the feature, and it is measured rather than
    guessed. Every one of `std/iter`'s iterators is in this class (`__iter__`
    on `var self` and on `ref self`, which is the wall `emit_resolve.
    _register_generic_struct` cannot pass); and the ones that are NOT are
    outside it for a reason this codegen has not fixed yet:

      dup = ['__iter__']                          _Empty, _Once,
                                                  _PeekableIterator, _MapIterator,
                                                  _ZipIterator, _ChainedIterator,
                                                  _Enumerate, _RepeatIterator
      dup = ['__init__']                          MoveCounter, ArcPointer,
                                                  BitSet, StaticTuple
      dup = ['__eq__', '__init__', '__iter__']    Optional
      dup = ['__getitem__', '__init__', '__iter__', 'extend', 'pop', 'resize']
                                                  List
      dup = ['__init__', '__len__', 'product']    Coord

    Those are REFUSED here — the `.o` route runs for them exactly as before —
    rather than materialized with a second definition or an arity the call site
    cannot satisfy. See
    `bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md` for
    the measurement of what widening this costs."""
    if base in _OVERLOAD_CACHE:
        return _OVERLOAD_CACHE[base]
    module_src = _module_src(gen, base, 'struct')
    ok = False
    if module_src:
        import elaborate
        tmpl = elaborate.extract_struct_source(module_src, base)
        if tmpl:
            try:
                parsed = Parser(py_tokenize(tmpl)).parse_module()
            except Exception:
                parsed = []
            for s in parsed:
                if isinstance(s, StructDef) and s.name == base:
                    seen: set = set()
                    dups: set = set()
                    for m in (getattr(s, 'methods', None) or []):
                        if m.name in seen:
                            dups.add(m.name)
                        seen.add(m.name)
                    ok = bool(dups) and dups <= _ITERATION_PROTOCOL
                    break
    _OVERLOAD_CACHE[base] = ok
    return ok


_OVERLOAD_CACHE: dict = {}


def _mentions_unbuildable_struct(work, ann, src_path=None):
    """Every mention in `ann` of a struct the `.o` route cannot serve. Used to
    decide whether a generic FUNCTION has to be materialized in-TU: `empty`'s
    `.o` elaboration succeeds, but its RETURN annotation names `_Empty`, whose
    registration is refused, so the caller would still get a boxed integer.

    `src_path` is the file `ann` came from, and registering the bases against
    IT is the whole reason this works for `from std.iter import empty`: that
    import line names `empty` and nothing else, so `_Empty` has to be
    discovered from `empty`'s own return annotation before its source file can
    even be looked up."""
    bases = []
    for base, args, _s, _e in _mentions(ann or ''):
        if base not in bases:
            bases.append(base)
    if src_path:
        _register_named(work.gen, src_path, bases)
    for base, args, _s, _e in _mentions(ann or ''):
        if args and base in work.gen._imported_generic_structs \
                and _protocol_only_overloads(work.gen, base):
            return True
    return False


def _fn_returns_unbuildable_struct(work, base) -> bool:
    """Does `base`'s own return annotation name a struct the `.o` route cannot
    register? Then `base` has to be materialized in-TU even though its OWN
    elaboration would succeed, because the caller would still receive a boxed
    integer where the iterator belongs.

    `empty` is the whole case: `def empty[T: Movable]() -> _Empty[T]`
    elaborates, compiles and links; `_Empty` does not register; so
    `var it = empty[Int]()` types `it` as `int64_t` and `next(it)` has no
    receiver to dispatch on."""
    if base in _FN_NEEDS_CACHE:
        return _FN_NEEDS_CACHE[base]
    ok = False
    module_src = _module_src(work.gen, base, 'fn')
    if module_src:
        import elaborate
        tmpl = elaborate.extract_fn_source(module_src, base)
        if tmpl:
            try:
                parsed = Parser(py_tokenize(tmpl)).parse_module()
            except Exception:
                parsed = []
            src_path = work.gen._imported_generics.get(base)
            for s in parsed:
                if isinstance(s, FunctionDef) and s.name == base:
                    ok = _mentions_unbuildable_struct(work, s.return_type, src_path)
                    break
    _FN_NEEDS_CACHE[base] = ok
    return ok


_FN_NEEDS_CACHE: dict = {}


# ── dependent-return iterator factory seeding ────────────────────────────────
#
# `peekable(l)` / `enumerate(l)` / `take(l, 3)` / `drop(l, 2)` / `cycle(l)`
# return types that depend on the STATIC TYPE of their container argument. The
# `.o` route erases that dependency to a boxed `int64_t` (the elaborator has no
# access to the importer's container types), so the local receives no struct
# type and `next(<local>)` refuses. This pass evaluates the dependency
# statically (`mojo/middle/iter_factory.py`), registers the wrapper struct the
# record names for in-TU materialization, enqueues it as a root, and records
# the call site for the emit side to reconstruct the factory body
# (`iter(container)` + the wrapper constructor). The existing `_collect_inner`
# cascade then materializes the inner iterator the wrapper's annotation
# mentions. What it deliberately refuses — a parameter or global container, a
# non-List container, and the multi-container / variadic / closure factories —
# is documented in iter_factory.py's own header; a refusal means the call site
# behaves exactly as it did before this pass existed.

def _abs_module_ref(ref: str, base: str) -> str:
    """Resolve a possibly-relative import ref against a base package (a copy of
    `emit_funcs._abs_module`, so this pre-pass does not import a backend module
    and reopen the `gimple_codegen` import cycle)."""
    if not ref.startswith('.'):
        return ref
    dots = len(ref) - len(ref.lstrip('.'))
    leaf = ref[dots:]
    parts = base.split('.')
    keep = parts[:len(parts) - (dots - 1)] if dots > 1 else parts
    return '.'.join(keep + ([leaf] if leaf else []))


def _import_name_map(stmts) -> dict:
    """local name -> importing module for every `from X import ...`, at
    module level AND inside function bodies. The function-level scan is
    load-bearing: test_drop's `test_drop_then_take_composition` imports
    `take` INSIDE the test fn (`from std.itertools import take`), which the
    top-level-only `_register_imported_generics` never sees, so
    `_factory_home` had no route to the factory's home module and the call
    site fell to the plain imported-name path — an `extern int64_t
    take (...)` the linker cannot satisfy (measured, 2026-10-21). First
    declaration (outermost, then source order) wins. The generic factories
    (`take`/`enumerate`/`drop`/`cycle`) are normally in
    `_imported_generics`, registered before this pass runs;
    `_imported_overloads` (where `peekable` would land) is NOT yet populated
    at this point, so it cannot be used to gate on."""
    out = {}

    def rec(node):
        if node is None:
            return
        if isinstance(node, FromImportStmt):
            mod = getattr(node, 'module', None)
            if mod:
                for entry in (getattr(node, 'name_alias_strs', None) or []):
                    nm = gimple_ctypes._fi_name(entry)
                    alias = gimple_ctypes._fi_alias(entry)
                    local = alias or nm
                    if local and local not in out:
                        out[local] = mod
            return
        for c in _children(node):
            rec(c)

    for st in stmts or ():
        rec(st)
    return out


_BUILTIN_FACTORY_HOME = {
    # `map` joined 2026-10-21 (further): test/iter/test_map.mojo calls
    # `map[add_one](l)` with NO import line — a compiler builtin whose
    # measured dependent-return implementation is std/iter's two overloads
    # (the positional `_MapIterator[function]` shape), exactly like
    # enumerate/iter below.
    'map': 'std.iter',
    # `chain`/`zip` joined 2026-10-21 (further, part 4): test/iter/
    # test_zip.mojo calls `zip(l, l2)` with NO import line (test_chain.mojo
    # DOES import chain — same builtin, either spelling), and the measured
    # implementation is std/iter's OUT-PARAMETER overloads (the out-res
    # subpath), so the no-import resolution lands exactly where the
    # import-line one does.
    'chain': 'std.iter', 'zip': 'std.iter',
    'enumerate': 'std.iter', 'iter': 'std.iter',
}


def _factory_home(gen, import_map, base):
    """The path of the module that DEFINES `def base`, or None. Generic
    factories (`def take[...](...)`) are already in `_imported_generics`; the
    non-generic overload (`def peekable(...)`) is not, so resolve it from the
    test's own import line, following re-export hops the way
    `_find_generic_source` does but accepting a `def base(` without brackets.

    BUILTINS: Mojo's `enumerate`, `iter`, and `map` are compiler builtins — a
    test file may call them with NO import line at all (test/iter/test_map
    and test_enumerate do). The stdlib's `std/iter` overloads ARE the
    builtin's measured dependent-return implementation, so a name with no
    import resolves there instead of refusing. `iter` then files no record anyway: its return
    (`type_of(iterable).IteratorOwnedType`) is not a wrapper mention, so
    `_factory_returns` answers the empty is-not-a-factory list and the call
    site keeps its old behavior (the `next(iter(<list>))` branch)."""
    p = getattr(gen, '_imported_generics', {}).get(base)
    if p:
        return p
    mod = import_map.get(base)
    if not mod:
        mod = _BUILTIN_FACTORY_HOME.get(base)
        if not mod:
            return None

    def resolve(mod, depth):
        if depth > 3 or not mod:
            return None
        try:
            path, src, _m = gen._parsed_import(mod)
        except Exception:
            return None
        if not src:
            return None
        if re.search(r'\bdef\s+' + re.escape(base) + r'\s*(?:\[|\()', src):
            return path
        _fi = _scan_from_imports_flat(src)
        _j = 0
        while _j + 1 < len(_fi):
            _fmod = _fi[_j]
            _fnames = _fi[_j + 1]
            _j += 2
            if re.search(r'(?:^|[\s,(])' + re.escape(base) + r'(?:[\s,)]|$)',
                         _fnames or ''):
                r = resolve(_abs_module_ref(_fmod, mod), depth + 1)
                if r:
                    return r
        return None
    return resolve(mod, 0)


def _container_home(gen, tname):
    """(path, source) of the module declaring `struct TNAME[...]`, resolved by
    the stdlib's `std/collections/<lower>` convention (List -> list.mojo), or
    (None, None). The source is returned to avoid a second `open`."""
    for cand in ('std.collections.' + tname.lower(), 'std.' + tname.lower()):
        try:
            path, src, _m = gen._parsed_import(cand)
        except Exception:
            continue
        if path and src and re.search(
                r'\bstruct\s+' + re.escape(tname) + r'\s*\[', src):
            return path, src
    return None, None


_FACTORY_RETURN_CACHE: dict = {}


def _factory_returns(fsrc, path, base):
    """Every `def base` overload, as a list of {'pr': <parse_return result>,
    'params': [param names]} (overloads whose return is not a dependent one
    dropped), cached per (home, name) — the same factory is called many times
    in one test file and its module is large. An EMPTY list is the
    load-bearing answer: it means `base` is imported but NOT a
    dependent-return factory, which is the gate that keeps an
    `assert_equal(<list>, ...)` call from ever being misread as a factory
    call site (and from filing a false container-resolution refusal)."""
    key = path + '\x1f' + base
    if key not in _FACTORY_RETURN_CACHE:
        try:
            stmts = Parser(py_tokenize(fsrc)).parse_module()
        except Exception:
            stmts = []
        out = []
        for s in stmts:
            if isinstance(s, FunctionDef) and getattr(s, 'name', None) == base:
                pr = iter_factory.parse_return(getattr(s, 'return_type', None))
                if pr is None:
                    # The OUT-PARAMETER spelling (measured 2026-10-21,
                    # part 4: chain/zip — no return annotation; the
                    # dependent wrapper is the trailing `out` parameter's
                    # annotation, whose `out` marker the parser drops).
                    pr = iter_factory.parse_out_res(
                        getattr(s, 'params', None) or [],
                        getattr(s, 'return_type', None))
                if pr is not None:
                    out.append({'pr': pr,
                                'params': [p[0] for p in
                                           (getattr(s, 'params', None) or [])],
                                # The factory's own parameter DEFAULTS, as the
                                # parsed literal nodes (measured 2026-10-21:
                                # count -> {'start': IntLiteral(0),
                                # 'step': IntLiteral(1)}). The direct-struct
                                # subpath fills a call's missing parameters
                                # with these — the factory body does exactly
                                # `return {start, step}` with the defaults in
                                # place, so this is a copy of what the body
                                # would construct, not a guess.
                                'defaults': dict(getattr(s, 'param_defaults',
                                                         None) or {})})
        _FACTORY_RETURN_CACHE[key] = out
    return _FACTORY_RETURN_CACHE[key]


def _factory_return_for(fsrc, path, base, moved):
    """The `def base` overload whose pass mode matches (`moved` -> the
    `var`/owned overload, else the `ref` one), or None when there is none of
    that mode. Both overloads of a factory name the SAME wrapper; they differ
    only in the type argument (IteratorType vs IteratorOwnedType), which is
    exactly the `kind`. When NO overload carries a kind (measured 2026-10-21
    (further): map's two overloads annotate IDENTICALLY, `_MapIterator[
    function]`, whose positional cannot express a pass mode) the first such
    overload answers — the pass mode is the call argument's `moved`, which
    the seed already carries in the record, and the overloads are
    functionally identical from here (same wrapper, same parameter names)."""
    want = 'owned' if moved else 'borrowed'
    overloads = _factory_returns(fsrc, path, base)
    for ov in overloads:
        if ov['pr']['kind'] == want:
            return ov
    for ov in overloads:
        if ov['pr']['kind'] is None:
            return ov
    return None


def _factory_return_out_for(fsrc, path, base, moved):
    """The OUT-PARAMETER overload whose pass mode matches (part 4: the
    chain/zip pair — the borrowed overload's `out res` annotation threads
    `_iterable_to_iterator`, the owned one `_iterable_owned_to_iterator`;
    `parse_out_res` read the kind off that marker). Same two-stage shape as
    `_factory_return_for`: the mode match first, then any out-res overload
    (a kind-less out-res spelling would still bind the inners from the
    call arguments' own moved flags)."""
    want = 'owned' if moved else 'borrowed'
    overloads = [ov for ov in _factory_returns(fsrc, path, base)
                 if ov['pr'].get('out_param')]
    for ov in overloads:
        if ov['pr']['kind'] == want:
            return ov
    return overloads[0] if overloads else None


def _collect_locals(node, out):
    """Every VarDecl reachable from `node` (recursing into nested blocks),
    first declaration winning — the container of a factory call is a local of
    the enclosing function."""
    stack = [node]
    while stack:
        n = stack.pop()
        if n is None:
            continue
        if isinstance(n, VarDecl):
            nm = getattr(n, 'name', None)
            if nm and nm not in out:
                out[nm] = n
        stack.extend(c for c in _children(n) if c is not None)


def _walk_scoped(stmts, visit):
    """`visit(call, scope)` for every CallExpr, where `scope` is the
    innermost enclosing function's `(name, func_node, locals_map)` (None at
    module level) — `locals_map` is that function's local VarDecls. The
    function NODE is carried too: a function VALUE passed as an explicit type
    arg (`drop_while[is_zero](nums)`) may be a NESTED def, and its lifted C
    name (`closure_lifted_name`) needs the enclosing chain plus the scope
    names for the capture check. Each nested function starts a fresh scope
    from its own body, so a same-named local in two functions does not
    conflate."""
    def rec(node, scope):
        if node is None:
            return
        if isinstance(node, FunctionDef):
            l = {}
            _collect_locals(getattr(node, 'body', None), l)
            scope = (getattr(node, 'name', None), node, l)
            for c in _children(node):
                rec(c, scope)
            return
        if isinstance(node, CallExpr):
            visit(node, scope)
        for c in _children(node):
            rec(c, scope)
    for s in stmts:
        rec(s, None)


def _wrapper_type_params(fsrc: str, wrapper: str) -> list | None:
    """The wrapper header's type parameter names, in declaration order, or
    None when the header block is unreadable. Comment params (`//`) carry no
    `name:` and are skipped."""
    m = re.search(r'struct\s+' + re.escape(wrapper) + r'\s*\[', fsrc)
    if not m:
        return None
    close = iter_factory._matching_bracket(fsrc, m.end() - 1)
    if close is None:
        return None
    out = []
    for part in iter_factory._top_level_split(fsrc[m.end():close]):
        # `\*?` keeps a variadic parameter's star (`*Ts: Iterator` — the
        # chain/zip out-res wrappers, measured 2026-10-21 part 4); the
        # pre-part-4 forms are all bare names, so this is a no-op for them.
        pm = re.match(r'(\*?\w+)\s*:', part.strip())
        if pm:
            out.append(pm.group(1))
    return out or None


def _wrapper_header_params(fsrc: str, wrapper: str) -> list | None:
    """The wrapper struct's bracket-header parameters as (name, annotation)
    pairs in declaration order, or None when the header is unreadable. The
    name keeps its variadic star (`*Ts`); the annotation is single-spaced.
    The out-res seed (part 4) reads this to tell the INNER-variadic
    parameter (`*Ts: Iterator`) from a VALUE parameter (zip's
    `origin: Origin`, which the factory's dependent annotation threads but
    the wrapper body never reads — measured: the spliced body references
    no `origin`, so it binds to its own annotation's first word)."""
    m = re.search(r'struct\s+' + re.escape(wrapper) + r'\s*\[', fsrc)
    if not m:
        return None
    close = iter_factory._matching_bracket(fsrc, m.end() - 1)
    if close is None:
        return None
    out = []
    for part in iter_factory._top_level_split(fsrc[m.end():close]):
        pm = re.match(r'(\*?\w+)\s*:\s*(.*)$', part.strip(), re.S)
        if pm:
            out.append((pm.group(1), ' '.join(pm.group(2).split())))
    return out or None


def _wrapper_param_roles(fsrc: str, wrapper: str) -> tuple | None:
    """The wrapper header's type parameters classified by their annotations,
    as `(inner_name, fn_names, derived_names)`, or None when the header block
    is unreadable or the inner is ambiguous. Measured 2026-10-21 (further):

    * `InnerIteratorType: Iterator` (take/drop/cycle/enumerate,
      take_while/drop_while, map) — the INNER: the container's own iterator,
      bound from the container argument;
    * `predicate: def(...) thin -> Bool` / `function: def(...) thin ->
      OutputType` (take_while/drop_while, map) — a FUNCTION value, bound
      from the call's explicit type argument (the wrapper body's
      `Self.predicate(elem)` / `Self.function(...)` monomorphizes, the
      `Self.<param>` unit pass, to a direct call of that value);
    * `OutputType: Copyable` (map) — DERIVED: its type argument is nowhere
      in the call, so it is bound from the bound function value's OWN return
      annotation.

    Comment parameters (`//`) carry no `name:` and are skipped, as in
    `_wrapper_type_params`. At most one of each kind is bindable — the
    caller refuses on a second of any kind. Product's second `Copyable &
    Iterator` parameter classifies derived and stays refused downstream: its
    call passes no function value to derive it from."""
    m = re.search(r'struct\s+' + re.escape(wrapper) + r'\s*\[', fsrc)
    if not m:
        return None
    close = iter_factory._matching_bracket(fsrc, m.end() - 1)
    if close is None:
        return None
    inner, fns, derived = None, [], []
    for part in iter_factory._top_level_split(fsrc[m.end():close]):
        pm = re.match(r'(\w+)\s*:\s*(.*)$', part.strip(), re.S)
        if not pm:
            continue
        ann = ' '.join(pm.group(2).split())
        if re.match(r'def\b', ann):
            fns.append(pm.group(1))
        elif ann.startswith('Iterator'):
            if inner is not None:
                return None
            inner = pm.group(1)
        else:
            derived.append(pm.group(1))
    return inner, fns, derived


def _wrapper_iter_params(fsrc: str, wrapper: str) -> list | None:
    """The wrapper header's Iterator-annotated type parameters, in
    DECLARATION order (measured 2026-10-21, part 4: product's
    `_Product2[IteratorTypeA: Iterator, IteratorTypeB: Copyable &
    Iterator]` — BOTH are inner slots, one per container argument).
    `_wrapper_param_roles` classifies the `Copyable & Iterator` one as
    derived because its annotation does not START with `Iterator` — the
    right answer for the single-inner subpath (the caller refuses it),
    but the multi subpath needs the FULL ordered list. Function-value
    parameters (`def(...)`) are skipped; None when the header block is
    unreadable."""
    m = re.search(r'struct\s+' + re.escape(wrapper) + r'\s*\[', fsrc)
    if not m:
        return None
    close = iter_factory._matching_bracket(fsrc, m.end() - 1)
    if close is None:
        return None
    out = []
    for part in iter_factory._top_level_split(fsrc[m.end():close]):
        pm = re.match(r'(\w+)\s*:\s*(.*)$', part.strip(), re.S)
        if not pm:
            continue
        ann = ' '.join(pm.group(2).split())
        if re.match(r'def\b', ann):
            continue
        if 'Iterator' in ann:
            out.append(pm.group(1))
    return out


def _find_fn_def(name, scope, stmts):
    """The FunctionDef `name` refers to — a NESTED def of the innermost
    enclosing function (the scope's func-node body), else a MODULE-level def,
    else None. The positional-argument subpath's safety gate: the bare
    identifier a kind-None return (`_MapIterator[function]`) passes must
    resolve to one of these, so a bare TYPE arg can never bind the function
    slot (the kw arm predates this gate and cannot spell a type arg)."""
    if scope is not None:
        _fn_name, func_node, _locals = scope
        for s in (getattr(func_node, 'body', None) or []):
            if isinstance(s, FunctionDef) and getattr(s, 'name', None) == name:
                return s
    for s in (stmts or []):
        if isinstance(s, FunctionDef) and getattr(s, 'name', None) == name:
            return s
    return None


def _fn_return_annot(name, scope, stmts):
    """The bound function value's OWN `-> T` annotation, as single-spaced
    source text, or (None, refusal). Measured 2026-10-21 (further):
    `def add_one(x: Int) -> Int` nested in test_map — the wrapper's derived
    parameter (`_MapIterator`'s `OutputType: Copyable`) is not in the call
    and not derivable from the inner, so it comes from here."""
    fn = _find_fn_def(name, scope, stmts)
    if fn is None:
        return None, f'function value {name!r} has no definition in this module'
    ann = getattr(fn, 'return_type', None)
    if not isinstance(ann, str) or not ann.strip():
        return None, (f'function value {name!r} has no return annotation — '
                      "the wrapper's derived type parameter cannot be bound")
    return ' '.join(ann.split()), None


def _fn_returns_map(stmts) -> dict:
    """Every MODULE-LEVEL `def` in this module, mapped to its `-> T` return
    annotation as single-spaced source text (an annotationless def maps to
    ''). Measured 2026-10-22 part 5: `cycle(_owned3(1, 2, 3))` — the
    container is a local function's OWNED RETURN, and only that function's
    own return annotation (`-> _CopyableOwned[3]`) states the container's
    concrete instantiation. `resolve_container`'s struct-fn branch consumes
    this map to gate the shape (a return annotation that is not a local
    generic-struct mention answers None, the honest pre-part-5 refusal).
    Nested defs (not top-level statements) never answer a factory container
    in this codegen, so they are deliberately excluded."""
    out = {}
    for st in stmts or ():
        if type(st).__name__ != 'FunctionDef':
            continue
        ann = getattr(st, 'return_type', None)
        out[st.name] = (' '.join(ann.split())
                        if isinstance(ann, str) else '')
    return out


def _call_fn_arg(node) -> str | None:
    """The function value a factory call passes as its single explicit type
    arg (measured 2026-10-21 (further): `take_while[less_than_5](nums)`),
    or None for any shape the subpath cannot name — zero or several args,
    a lambda, a member access. A bare identifier is the local/global
    function the materialized wrapper body calls directly; its C symbol is
    `_func_csym`'s, which the definition and every call site (the spliced
    body included) agree on."""
    fn = getattr(node, 'func', None)
    if type(fn).__name__ != 'SubscriptExpr':
        return None
    idx = getattr(fn, 'index', None)
    if idx is None:
        return None
    if type(idx).__name__ != 'IdentExpr':
        return None
    return getattr(idx, 'name', None)


def _fn_value_name(fn_name, scope):
    """The name to bind a function VALUE type argument to, so the materialized
    wrapper body's `Self.predicate(elem)` call actually reaches the function.
    Returns (name, refusal_reason). Measured 2026-10-21 (further):

    * a MODULE-level `def` — the bare name. The plain-call path resolves it
      via `_func_csym` (module-qualified + overload suffix) at the definition
      and at the spliced call site alike — the `take_while[less_than_5]`
      shape, ladder-verified 14/14.
    * a NON-capturing nested `def` — its LIFTED C name, the one shape
      `closures.closure_lifted_name` gives a nested def and the single name
      its definition is emitted under (`<enclosing>_<name>`, forward-declared
      in the TU; the call resolves through `func_return_types`' lifted
      signature that `discover_closures` registers). Binding the BARE name
      here instead emits the catch-all weak stub — the measured `is_zero:
      unavailable in compiled mode` shape, where the definition IS in the TU
      under the lifted name and the bare call simply never finds it.
    * a CAPTURING nested `def` — refusal: a capturing closure is a
      bound-method VALUE (env pointer + code pointer), not a callable by
      name, and the spliced body can only call a plain function.
    """
    if scope is None:
        return fn_name, None
    _func_name, func_node, locals_map = scope
    body = getattr(func_node, 'body', None) or []
    target = None
    for s in body:
        if isinstance(s, FunctionDef) and getattr(s, 'name', None) == fn_name:
            target = s
            break
    if target is None:
        # Not nested in THIS function: either a module-level def (the bare
        # name resolves, as in the first bullet) or a def nested deeper than
        # one level under a call the scope chain never crossed — the bare
        # name is the honest answer for both (the former works; the latter
        # degrades to the pre-subpath shape, not a miscompile).
        return fn_name, None
    # Capture check: a free identifier bound by THIS function's declared
    # names (its locals or parameters) is a capture. A name in none of them
    # is a module global the lifted body reaches through the ordinary
    # globals route (discover_closures makes the same call — its `free`
    # names that miss `enriched_scope` are globals, not captures).
    declared = set(locals_map or ())
    for p in (getattr(func_node, 'params', None) or []):
        _pn = p[0] if isinstance(p, (list, tuple)) else p
        declared.add(_pn.lstrip('*'))
    tparams = set()
    for p in (getattr(target, 'params', None) or []):
        _pn = p[0] if isinstance(p, (list, tuple)) else p
        tparams.add(_pn.lstrip('*'))
    tlocals = {}
    _collect_locals(getattr(target, 'body', None), tlocals)
    tparams |= set(tlocals)
    used = set()
    for bstmt in (getattr(target, 'body', None) or []):
        used |= gimple_ctypes._used_idents_node(bstmt)
    caps = sorted((used - tparams) & declared)
    if caps:
        return None, (f'function value {fn_name!r} is a capturing closure '
                      f'(captures {", ".join(caps)}) — the materialized '
                      'wrapper body calls the predicate by name, which '
                      'only a plain (non-capturing) function answers')
    return closure_lifted_name(_func_name, fn_name), None


def _seed_one_factory(gen, work, mm, base, node, scope, stmts, import_map,
                      queue, records, depth=0):
    """Evaluate ONE factory call site. Returns the record (filed in `records`
    and its wrapper enqueued as a root) or None for every refusal — in which
    case the call site is left exactly as this pass found it. The checks run
    cheapest-first, and the IS-FACTORY gate comes before the container
    resolution, so a non-factory call (`assert_equal(<list>, ...)`) never
    files a container-resolution refusal. `scope` is the innermost enclosing
    function's `(name, func_node, locals_map)` (None at module level) — the
    function VALUE subpath needs the node and the scope names to lift a
    nested `def`'s name and to rule out a capturing closure. `stmts` is the
    module's own top-level statements — the function-value lookups
    (`_find_fn_def` / `_fn_return_annot`) fall back to them for MODULE-level
    defs."""
    if depth > 4:
        work.refuse(f'{base}(...): nested factory depth exceeds 4')
        return None
    locs = scope[2] if scope is not None else None
    args = getattr(node, 'args', None) or []
    home = _factory_home(gen, import_map, base)
    if not home:
        # Part 6 family D (2026-10-23, measured on test_product's
        # test_product2_copies): a DIRECT WRAPPER CONSTRUCTOR — the base is
        # an imported generic STRUCT (its home lives in
        # `_imported_generic_structs`, which `_factory_home` above never
        # reads — it answers None for a struct), and the call is the bare
        # constructor spelling with no dependent-return factory in between.
        # On the old path the call names the BARE template symbol (`extern
        # int64_t _Product2 (...);`, no definition in any TU) — a link hazard
        # the -fsyntax-only gate cannot see. Gated on the struct living in
        # ANOTHER module than the caller: a same-module generic struct
        # compiles to one concrete C struct whose constructor IS defined in
        # this TU, so the ordinary local-struct constructor path is its
        # correct answer (measured: this file's own `TestCopyIterator(
        # copy_a)` calls, which must keep their old path).
        _shome = getattr(gen, '_imported_generic_structs', {}).get(base)
        if (_shome
                and os.path.normpath(str(_shome)) != os.path.normpath(
                    str(getattr(gen, '_current_filename', '') or ''))):
            try:
                _ssrc = open(_shome).read()
            except OSError:
                return None
            return _seed_direct_ctor(gen, work, mm, base, node, _ssrc,
                                     _shome, scope, stmts, import_map,
                                     queue, records)
        return None
    try:
        fsrc = open(home).read()
    except OSError:
        return None
    if not _factory_returns(fsrc, home, base):
        return None   # imported, but not a dependent-return factory
    if not args:
        # A ZERO-ARGUMENT call is a factory only through the direct-struct-
        # return subpath (measured 2026-10-21: test_count's `var it =
        # count()` — the return is a concrete struct, there is no container
        # argument to resolve, and the old `len(args) < 1` early-return here
        # seeded nothing, so `it` stayed int64_t and `next(it)` refused).
        # Anything that is not a direct-struct factory returns None from
        # there — exactly the pre-subpath behavior.
        return _seed_direct_factory(gen, work, mm, base, node, fsrc, home,
                                    queue, records)
    # The OUT-PARAMETER factory (part 4: chain/zip — no return annotation;
    # every overload is the `out res: Wrapper[...]` spelling): a separate
    # subpath (N container arguments -> N inners, a variadic `*Ts`
    # binding). Gated on ALL overloads being out-res so a factory that
    # mixes the two spellings (unmeasured) keeps the return-value path.
    if all(o['pr'].get('out_param')
           for o in _factory_returns(fsrc, home, base)):
        return _seed_out_res_factory(gen, work, mm, base, node, scope, stmts,
                                     import_map, queue, records, fsrc, home,
                                     depth)
    # The MULTI-CONTAINER dependent-return factory (part 4: `product(a, b)`
    # — `-> _Product2[<inner mention of arg0>, <inner mention of arg1>]`):
    # EVERY argument is a container, which the single-first-argument flow
    # below cannot see. Gated on an arity-matching multi overload so the
    # single-argument factories (take/drop/cycle/enumerate/map/...) keep
    # the return-value path untouched.
    if any(o['pr'].get('multi') and len(o['params']) == len(args)
           for o in _factory_returns(fsrc, home, base)):
        return _seed_multi_factory(gen, work, mm, base, node, scope, stmts,
                                   import_map, queue, records, fsrc, home,
                                   depth)
    # `factory_names` is an over-approximation (every imported generic); the
    # nested recursion re-validates each one, so a non-factory nested call
    # simply refuses the outer. It exists so `resolve_container` can tell a
    # nested factory call from an ordinary local.
    factory_names = set(getattr(gen, '_imported_generics', {}))
    # Part 5 (2026-10-22): the struct-fn container kind needs the module's
    # own struct names (gate) and its module-level defs' return annotations
    # (the container's concrete instantiation). Both are None-safe —
    # without them `resolve_container` answers exactly the pre-part-5
    # refusal for a local-fn-call argument.
    _struct_names = {st.name for st in (stmts or ())
                     if type(st).__name__ == 'StructDef'}
    cont = iter_factory.resolve_container(
        args[0], factory_names, locs, struct_names=_struct_names,
        fn_returns=_fn_returns_map(stmts))
    if cont is None:
        work.refuse(
            f'{base}(...): container argument is not a statically resolvable '
            'local List / range / nested factory')
        return None
    pr = _factory_return_for(fsrc, home, base, cont['moved'])
    if pr is None:
        work.refuse(f'{base}(...): no {"owned" if cont["moved"] else "borrowed"}-container '
                    'overload with a dependent return')
        return None
    # List-container factory — the data path this used to refuse is now
    # lowerable, so the record is filed and the wrapper/inner below are
    # materialized. 2026-10-20 (further) — LIFTED. The refusal this block
    # used to be (keep its measured evidence in
    # bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered
    # .md, "2026-10-20 (continued)") is gone because the in-TU iterator
    # protocol now has a lowerable data path, in RUNTIME-LIST terms:
    #   * `List` is deliberately NOT registered in
    #     `_imported_generic_structs` (neither here nor in
    #     `_collect_inner`'s mention walk — see its List guard), so the
    #     materialized inner's `var _list: List[Int]` field annotation
    #     erases through `types._mojo_type` to `MojoList *` — the runtime
    #     container — instead of materializing a formal-layout
    #     `List_1_T_3_Int {type_id, _storage, _len}` shell that does not
    #     match the runtime object `{data, len, cap, inl}`.
    #   * `_materialize` rewrites the spliced inner bodies to lowerable
    #     expressions over that field: `self._list[i]` (MojoList * branch
    #     of _lower_subscript -> mojo_list_get_*), `len(self._list)`
    #     (_lower_builtin_len -> mojo_list_len), `self._data[i]` (plain
    #     pointer subscript -> _mojo_at_ + deref) in place of the
    #     `unsafe_ptr/unsafe_offset/unsafe_take_pointee` chains and the
    #     `unsafe_offset=` kwarg subscript, none of which has a lowering.
    #   * `List[T]()` at the call site keeps the baseline runtime
    #     constructor (mojo_list_new + mojo_list_append_*), because no
    #     in-TU `List` struct exists to claim it.
    # Verified per file with the gcc -c + nm + ld + run ladder, never
    # the syntax-only gate: the module's own object defines the
    # instantiation and its __next__, the real link leaves no undefined
    # iterator symbol, and the asserted values are the real ones.
    wrapper = pr['pr']['wrapper']
    # The factory's trailing parameter (`count` for take/drop, `start` for
    # enumerate) is the wrapper `__init__`'s keyword — the factory body calls
    # `_TakeIterator(<iter>, count=count)`. cycle/peekable have none.
    _pnames = pr['params']
    wrapper_kwarg = _pnames[1] if len(_pnames) > 1 else None
    wrapper_param = None
    fn_param = None
    fn_arg = None
    derived_param = None
    derived_annot = None
    if wrapper is not None:
        roles = _wrapper_param_roles(fsrc, wrapper)
        if roles is None:
            work.refuse(
                f'{base}(...): wrapper {wrapper!r} type-parameter header '
                'unreadable or ambiguous in its home module')
            return None
        wrapper_param, _fns, _derived = roles
        if wrapper_param is None:
            work.refuse(
                f'{base}(...): wrapper {wrapper!r} has no `Iterator`-annotated '
                'type parameter to carry the inner')
            return None
        if len(_fns) > 1:
            work.refuse(
                f'{base}(...): wrapper {wrapper!r} has more than one function '
                f'type parameter {_fns}')
            return None
        if len(_derived) > 1:
            work.refuse(
                f'{base}(...): wrapper {wrapper!r} has more than one derived '
                f'type parameter {_derived}')
            return None
        fn_param = _fns[0] if _fns else None
        derived_param = _derived[0] if _derived else None
        if fn_param is None and derived_param is not None:
            # A derived parameter is bound FROM the function value's own
            # return annotation — without a function value there is nothing
            # to derive it from (product's second `Copyable & Iterator`
            # parameter classifies derived and stays refused here:
            # `product(a, b)` passes no explicit type arg at all).
            work.refuse(
                f'{base}(...): wrapper {wrapper!r} has a derived type '
                f'parameter {derived_param!r} whose type argument is not in '
                'the call, but the call passes no function value to derive '
                'it from')
            return None
        # A wrapper with a FUNCTION type parameter beyond the inner
        # (measured 2026-10-21 (further): take_while/drop_while's `predicate:
        # def(...) thin -> Bool`, map's `function: def(...) thin ->
        # OutputType`) binds it from the call's explicit type arg:
        # `take_while[less_than_5](nums)` passes the function AS a type
        # argument, so the materialized body's `Self.predicate(elem)`
        # monomorphizes (the `Self.<param>` unit pass) to a direct call of
        # the local function.
        if fn_param is not None:
            fn_arg_raw = _call_fn_arg(node)
            if fn_arg_raw is None:
                work.refuse(
                    f'{base}(...): wrapper {wrapper!r} takes a function type '
                    f'parameter {fn_param!r}, but the call passes no bare-'
                    'identifier explicit type arg to bind it')
                return None
            if pr['pr']['kind'] is None:
                # The positional arm's shape (`_MapIterator[function]`): the
                # bare identifier must resolve to an ACTUAL def — a bare TYPE
                # arg (`Foo[T]`) has no def, and binding a type name into the
                # function slot would miscompile. The kw arm
                # (`predicate=predicate`) cannot spell a type arg and
                # predates this gate.
                if _find_fn_def(fn_arg_raw, scope, stmts) is None:
                    work.refuse(
                        f'{base}(...): explicit type arg {fn_arg_raw!r} does '
                        'not resolve to a function defined in this module — '
                        'the positional-argument subpath binds function '
                        'values only')
                    return None
            _fn_val, _fn_err = _fn_value_name(fn_arg_raw, scope)
            if _fn_err is not None:
                work.refuse(f'{base}(...): {_fn_err}')
                return None
            fn_arg = _fn_val
            if derived_param is not None:
                derived_annot, _ann_err = _fn_return_annot(fn_arg_raw, scope,
                                                           stmts)
                if _ann_err is not None:
                    work.refuse(f'{base}(...): {_ann_err}')
                    return None
    else:
        # The BARE `iter(<container>)` builtin: its return annotation names
        # the container's OWN iterator type directly (`type_of(x).
        # IteratorOwnedType` / `X.IteratorType[origin_of(x)]` — see
        # iter_factory.parse_return's `wrapper: None` shapes), so there is no
        # wrapper to look up, register, or construct: the inner IS the return
        # value. For a list container the inner is materialized as its own
        # queue root below (nothing else mentions it); for a nested-factory
        # container (`iter(<other factory's result>)`) the container's
        # `__iter__` returns Self, so the sub-factory's wrapper IS the inner
        # and the recursion below has already enqueued it.
        pass
    sname_mangled = None   # struct-fn kind: the container's own mangle
    if cont['kind'] in ('list', 'set', 'pyobj-list'):
        # A set container (measured 2026-10-21 (further): `enumerate(my_set)`
        # on `var my_set = {4, 5, 6}`) rides the list path end to end: the
        # emit side feeds `mojo_set_to_list(<set>)` — the runtime's
        # insertion-order materialization, the same order the runtime set
        # for-loop iterator walks (emit_loops' set branch) — into the
        # identical list reconstruction. So the INNER and the WRAPPER are
        # derived from the LIST source, not the set's own hash-bucket
        # iterator, whose body has no lowerable in-TU form. A pyobj-list
        # container (part 4, further: `enumerate(list_obj.__iter__())` — a
        # PythonObject local's own `__iter__()` call) is the same borrowed
        # list cursor derived from the LIST source: the emit side lowers
        # the receiver box and unboxes it to the MojoList * the cursor
        # walks.
        _ctname = 'List' if cont['kind'] in ('set', 'pyobj-list') \
            else cont['tname']
        chome, csrc = _container_home(gen, _ctname)
        if not csrc:
            work.refuse(
                f'{base}(...): no module declares container {cont["tname"]!r}')
            return None
        kind = 'owned' if cont['moved'] else 'borrowed'
        rhs = iter_factory.iter_type_rhs(csrc, _ctname, kind)
        if rhs is None:
            work.refuse(f'{base}(...): {cont["tname"]}.Iterator{"Owned" if kind == "owned" else ""}Type '
                        'member not found')
            return None
        inner_base = rhs.split('[', 1)[0].strip()
        inner = iter_factory.expand_inner(csrc, inner_base, rhs, cont['elem'],
                                          bool(cont['moved']))
        if inner is None:
            work.refuse(f'{base}(...): {inner_base} type arguments do not bind '
                        f'for {cont["tname"]}')
            return None
        inner_mention = inner_base + '[' + ', '.join(inner['args']) + ']'
        inner_mangled = mm.mangle(
            inner_base, dict(zip(inner['names'], inner['args'])))
        _register_named(gen, chome, [inner_base])
    elif cont['kind'] == 'struct-fn':
        # A LOCAL function call returning a module-local GENERIC struct
        # (measured 2026-10-22 part 5: test_cycle's
        # `cycle(_owned3(1, 2, 3))` - the container is `_CopyableOwned[3]`,
        # an `IterableOwned` whose `comptime IteratorOwnedType` member names
        # the inner `_CopyableOwnedIter[Self.size]` with the container's own
        # type parameter in place of `Self.size`). Both structs are
        # top-level statements of THIS module: the same-file registration in
        # `_register_imported_generic_structs` already put them in
        # `_imported_generic_structs` (the current file as their home), so
        # the in-TU materializer extracts them from this source, and the
        # queue roots below are their only mention sites. The container's
        # own mangled name goes in the record - the emit side lowers the fn
        # call, calls the container's in-TU `__iter__`, and feeds the
        # resulting inner into the wrapper constructor.
        _mod_src = ''
        try:
            if gen._current_filename:
                _mod_src = open(gen._current_filename).read()
        except OSError:
            _mod_src = ''
        if not _mod_src:
            work.refuse(f'{base}(...): module source unreadable for the '
                        f'struct-fn container {cont["sname"]!r}')
            return None
        rhs = iter_factory.iter_type_rhs(_mod_src, cont['sname'], 'owned')
        if rhs is None:
            work.refuse(
                f'{base}(...): {cont["sname"]}.IteratorOwnedType member '
                'not found')
            return None
        inner_base = rhs.split('[', 1)[0].strip()
        inner = iter_factory.struct_iter_inner(_mod_src, cont['sname'], rhs,
                                               cont['sargs'])
        if inner is None:
            work.refuse(
                f'{base}(...): {inner_base} type arguments do not bind for '
                f'{cont["sname"]}')
            return None
        inner_mention = inner_base + '[' + ', '.join(inner['args']) + ']'
        inner_mangled = mm.mangle(
            inner_base, dict(zip(inner['names'], inner['args'])))
        sname_mangled = mm.mangle(
            cont['sname'],
            iter_factory.struct_args_map(_mod_src, cont['sname'],
                                         cont['sargs']) or {})
        work.enqueue(('struct', cont['sname'], tuple(cont['sargs'])), 0,
                     queue)
        work.enqueue(('struct', inner_base, tuple(inner['args'])), 0, queue)
    else:   # nested factory: its wrapper is the container (its own
            # `comptime IteratorType[...] = Self`), so the inner is that
            # wrapper's mangled name, registered by the recursion below.
        sub = _seed_one_factory(gen, work, mm, cont['name'], cont['node'],
                                scope, stmts, import_map, queue, records,
                                depth + 1)
        if sub is None:
            return None
        inner_mention = sub['wrapper_mangled']
        inner_mangled = sub['wrapper_mangled']
    wrapper_mangled = None
    if wrapper is not None:
        _wtargs = {wrapper_param: inner_mention}
        if fn_param is not None:
            _wtargs[fn_param] = fn_arg
        if derived_param is not None:
            _wtargs[derived_param] = derived_annot
        wrapper_mangled = mm.mangle(wrapper, _wtargs)
        _register_named(gen, home, [wrapper])
    rec = {'name': base, 'wrapper': wrapper, 'wrapper_param': wrapper_param,
           'wrapper_mangled': wrapper_mangled, 'inner_mangled': inner_mangled,
           'inner_mention': inner_mention, 'kind': cont['kind'],
           'elem': cont.get('elem'),
           'elem_ctype': iter_factory._MOJO_ELEM_C.get(cont.get('elem'),
                                                       'int64_t'),
           'moved': bool(cont['moved']),
           'wrapper_kwarg': wrapper_kwarg,
           'sname': cont.get('sname'),
           'sname_mangled': sname_mangled}
    records[iter_factory.factory_call_key(base, node)] = rec
    if wrapper is None:
        # Bare `iter`: the inner (the iterator itself) is the queue root —
        # for a list container it is materialized at its element argument
        # (mangle-identical to the mention the wrappers of the same file
        # reference, so the queue's seen-set dedupes it); for a nested-
        # factory container the recursion above already enqueued the
        # container's own wrapper, which is the inner. A set container
        # materializes its inner the same way as a list (the seed branch
        # above derived it from the LIST source).
        if cont['kind'] in ('list', 'set', 'pyobj-list'):
            work.enqueue(('struct', inner_base, tuple(inner['args'])), 0, queue)
    else:
        if fn_param is None and derived_param is None:
            work.enqueue(('struct', wrapper, (inner_mention,)), 0, queue)
        else:
            # Positional order is the wrapper's DECLARATION order (bind_type_
            # args zips it against the header params). With the function
            # parameter that is (inner, predicate) for take_while/drop_while;
            # with the derived one, (OutputType, InnerIteratorType,
            # function) for map; the pre-subpath single-param wrappers never
            # reach this branch.
            _wparams = _wrapper_type_params(fsrc, wrapper)
            if _wparams is None:
                work.refuse(f'{base}(...): wrapper {wrapper!r} header '
                            'unreadable')
                return None
            _warg_map = {wrapper_param: inner_mention}
            if fn_param is not None:
                _warg_map[fn_param] = fn_arg
            if derived_param is not None:
                _warg_map[derived_param] = derived_annot
            if not set(_wparams) <= set(_warg_map):
                work.refuse(
                    f'{base}(...): wrapper {wrapper!r} has type parameters '
                    f'{_wparams} beyond this subpath\'s bindable '
                    f'{sorted(_warg_map)}')
                return None
            work.enqueue(('struct', wrapper,
                          tuple(_warg_map[p] for p in _wparams)), 0, queue)
    return rec


def _seed_multi_factory(gen, work, mm, base, node, scope, stmts, import_map,
                        queue, records, fsrc, home, depth):
    """The MULTI-CONTAINER dependent-return factory subpath (measured
    2026-10-21, part 4: `product(a, b[, c[, d]])` — `-> _ProductN[
    <per-argument inner mentions>]`; see parse_return's multi arm for the
    annotation shape). Every CALL ARGUMENT is a container, resolved
    independently; the per-argument inner is derived exactly the way the
    single-container return-value subpath derives its inner from args[0],
    and the WRAPPER is materialized once with the per-argument inner
    MENTIONS as its type arguments in the wrapper's declared parameter
    order (which is the call's argument order — the annotation's mention
    i names argument i's inner). The per-argument inners are NOT
    enqueued here: the wrapper's spliced source mentions each inner type
    in a field annotation, and `_collect_inner`'s mention walk enqueues
    them when the wrapper materializes — exactly the way the single-inner
    path relies on it (it enqueues only the wrapper too).

    A mixed pass mode (one argument moved, another not) is refused: the
    measured overloads are homogeneous (`ref ...` / `var ...` on ALL
    parameters) and the wrapper's type arguments are all IteratorType or
    all IteratorOwnedType — a heterogeneous inner tuple is unmeasured.
    """
    if depth > 4:
        work.refuse(f'{base}(...): nested factory depth exceeds 4')
        return None
    locs = scope[2] if scope is not None else None
    args = getattr(node, 'args', None) or []
    factory_names = set(getattr(gen, '_imported_generics', {}))
    # Part 5 (2026-10-22): the struct-fn container kind (a local function
    # call whose return annotation names a module-local generic struct -
    # test_product's `product(_owned3(1, 2, 3), _owned2(10, 20))`) needs
    # the same two maps as the single-container path.
    _struct_names = {st.name for st in (stmts or ())
                     if type(st).__name__ == 'StructDef'}
    conts = []
    for i, a in enumerate(args):
        c = iter_factory.resolve_container(
            a, factory_names, locs, struct_names=_struct_names,
            fn_returns=_fn_returns_map(stmts))
        if c is None:
            work.refuse(
                f'{base}(...): argument {i} is not a statically resolvable '
                'local List / range / set / nested factory')
            return None
        conts.append(c)
    if len({c['moved'] for c in conts}) > 1:
        work.refuse(f'{base}(...): the call mixes moved and borrowed '
                    'container arguments — the measured multi-container '
                    'overloads are homogeneous in pass mode')
        return None
    moved = conts[0]['moved']
    want = 'owned' if moved else 'borrowed'
    ov = None
    for o in _factory_returns(fsrc, home, base):
        if (o['pr'].get('multi') and len(o['params']) == len(args)
                and o['pr']['kind'] == want):
            ov = o
            break
    if ov is None:
        work.refuse(f'{base}(...): no {want}-container overload with a '
                    'multi-container dependent return of this arity')
        return None
    pr = ov['pr']
    wrapper = pr['wrapper']
    iter_params = _wrapper_iter_params(fsrc, wrapper)
    if iter_params is None:
        work.refuse(f'{base}(...): wrapper {wrapper!r} type-parameter '
                    'header unreadable in its home module')
        return None
    if len(iter_params) != len(args):
        work.refuse(
            f'{base}(...): wrapper {wrapper!r} has {len(iter_params)} '
            f'Iterator-annotated type parameters but the call passes '
            f'{len(args)} containers')
        return None
    _all = _wrapper_type_params(fsrc, wrapper)
    if _all is None or set(_all) != set(iter_params):
        work.refuse(
            f'{base}(...): wrapper {wrapper!r} has non-Iterator type '
            f'parameters {sorted(set(_all or []) - set(iter_params))} '
            'beyond the multi-container subpath\'s per-argument inners')
        return None
    mentions = []
    inner_mangleds = []
    sname_mangleds = []   # struct-fn args: the container's own mangle
    for i, c in enumerate(conts):
        sname_mangled = None   # struct-fn args only
        if c['kind'] in ('list', 'set'):
            _ctname = 'List' if c['kind'] == 'set' else c['tname']
            chome, csrc = _container_home(gen, _ctname)
            if not csrc:
                work.refuse(
                    f'{base}(...): no module declares container '
                    f'{c["tname"]!r}')
                return None
            _kind = 'owned' if c['moved'] else 'borrowed'
            rhs = iter_factory.iter_type_rhs(csrc, _ctname, _kind)
            if rhs is None:
                work.refuse(f'{base}(...): {c["tname"]}.'
                            f'Iterator{"Owned" if _kind == "owned" else ""}Type '
                            'member not found')
                return None
            inner_base = rhs.split('[', 1)[0].strip()
            inner = iter_factory.expand_inner(csrc, inner_base, rhs,
                                              c['elem'], bool(c['moved']))
            if inner is None:
                work.refuse(
                    f'{base}(...): {inner_base} type arguments do not bind '
                    f'for {c["tname"]}')
                return None
            inner_mention = inner_base + '[' + ', '.join(inner['args']) + ']'
            inner_mangled = mm.mangle(
                inner_base, dict(zip(inner['names'], inner['args'])))
            _register_named(gen, chome, [inner_base])
        elif c['kind'] == 'factory':
            sub = _seed_one_factory(gen, work, mm, c['name'], c['node'],
                                    scope, stmts, import_map, queue, records,
                                    depth + 1)
            if sub is None:
                return None
            inner_mention = sub['wrapper_mangled']
            inner_mangled = sub['wrapper_mangled']
        elif c['kind'] == 'struct-fn':
            # A local function call returning a module-local GENERIC struct
            # (measured 2026-10-22 part 5: test_product's
            # `product(_owned3(1, 2, 3), _owned2(10, 20))`): the same
            # per-argument derivation as the single-container struct-fn
            # branch of `_seed_one_factory` - the struct's `comptime
            # IteratorOwnedType` member names the inner, `Self.<param>`
            # bound to the fn's return-annotation arguments. The container
            # and inner are top-level structs of this module (same-file
            # registration), so their queue roots are enqueued here: the
            # wrapper's field annotations mention the inners (the container
            # struct is otherwise unmentioned - its `__iter__` is called
            # from the emit side, not spliced anywhere).
            _mod_src = ''
            try:
                if gen._current_filename:
                    _mod_src = open(gen._current_filename).read()
            except OSError:
                _mod_src = ''
            if not _mod_src:
                work.refuse(f'{base}(...): module source unreadable for the '
                            f'struct-fn argument {i}')
                return None
            rhs = iter_factory.iter_type_rhs(_mod_src, c['sname'], 'owned')
            if rhs is None:
                work.refuse(
                    f'{base}(...): argument {i}: {c["sname"]}.'
                    'IteratorOwnedType member not found')
                return None
            inner_base = rhs.split('[', 1)[0].strip()
            inner = iter_factory.struct_iter_inner(_mod_src, c['sname'],
                                                   rhs, c['sargs'])
            if inner is None:
                work.refuse(
                    f'{base}(...): argument {i}: {inner_base} type '
                    'arguments do not bind for '
                    f'{c["sname"]}')
                return None
            inner_mention = inner_base + '[' + ', '.join(inner['args']) + ']'
            inner_mangled = mm.mangle(
                inner_base, dict(zip(inner['names'], inner['args'])))
            work.enqueue(('struct', c['sname'], tuple(c['sargs'])), 0,
                         queue)
            work.enqueue(('struct', inner_base, tuple(inner['args'])), 0,
                         queue)
            sname_mangled = mm.mangle(
                c['sname'],
                iter_factory.struct_args_map(_mod_src, c['sname'],
                                             c['sargs']) or {})
        else:
            work.refuse(
                f'{base}(...): argument {i} container kind '
                f'{c["kind"]!r} has no multi-container lowering')
            return None
        mentions.append(inner_mention)
        inner_mangleds.append(inner_mangled)
        sname_mangleds.append(sname_mangled)
    wrapper_mangled = mm.mangle(
        wrapper, dict(zip(iter_params, mentions)))
    _register_named(gen, home, [wrapper])
    # The seed-only splice knowledge (part 4, product): the wrapper's own
    # `Self.Element` — the product element IS the tuple of the per-argument
    # element mentions, in argument order. The wrapper's `comptime Element`
    # alias spans lines (`Tuple[\n ... \n]`), so monomorphize's single-line
    # member-splice gate leaves every `Self.Element` use unspliced (the same
    # gap the out-res seed closes for zip — see its `self_element`); without
    # the override the spliced `__next__` annotation stays `Self.Element`,
    # `_resolve_type` erases it to int64_t, and the list-backed tuple return
    # (a `MojoList *` of the slot values) is statically mistyped.
    _elems = [c.get('elem') or 'Int' for c in conts]
    work.variadic_meta[(wrapper, tuple(mentions))] = {
        'element_map': {m: e for m, e in zip(mentions, _elems)},
        'self_element': 'Tuple[' + ', '.join(_elems) + ']'}
    rec = {'name': base, 'wrapper': wrapper, 'wrapper_param': None,
           'wrapper_mangled': wrapper_mangled, 'inner_mangled': None,
           'inner_mention': None, 'kind': conts[0]['kind'],
           'elem': conts[0].get('elem'),
           'elem_ctype': iter_factory._MOJO_ELEM_C.get(conts[0].get('elem'),
                                                       'int64_t'),
           'moved': moved, 'wrapper_kwarg': None,
           'multi_args': [{'kind': c['kind'], 'inner_mangled': im,
                           'elem_ctype': iter_factory._MOJO_ELEM_C.get(
                               c.get('elem'), 'int64_t'),
                           'moved': bool(c['moved']),
                           'sname': c.get('sname'),
                           'sname_mangled': sm}
                          for c, im, sm in zip(conts, inner_mangleds,
                                               sname_mangleds)]}
    records[iter_factory.factory_call_key(base, node)] = rec
    work.enqueue(('struct', wrapper, tuple(mentions)), 0, queue)
    return rec


def _seed_out_res_factory(gen, work, mm, base, node, scope, stmts, import_map,
                          queue, records, fsrc, home, depth=0):
    """The OUT-PARAMETER dependent-return factory subpath (measured
    2026-10-21, part 4: `chain(l1, l2)` / `zip(l, l2)` — `def chain[*Ts:
    Iterable](*iterables: *Ts, out res: _ChainedIterator[*inners])`; the
    factory BODY is never executed — `_lower_factory_call`'s out-res branch
    reconstructs it from the call arguments: allocate the wrapper, write
    `res._idx = 0` (chain only), then one inner per container argument into
    the wrapper's tuple field (`res._iterators[i]` / `res._values[i]`).

    One wrapper instantiation per call (the same record the return-value
    subpath files), with the inners as a VARIADIC binding: the wrapper's
    `*Ts` type parameter consumes EVERY container argument, and
    `monomorphize._sub_variadic` splices the measured forms (`Tuple[*Self.
    Ts]`, `Self.Ts[0].Element`, the comptime-for unroll). `work.
    variadic_meta` carries the seed-only knowledge (each inner's ELEMENT
    mention, and the wrapper's own Element — zip's `Self.Element` needs the
    explicit override because its definition spans lines) to
    `_materialize`, the only place the concrete source is rebuilt."""
    args = getattr(node, 'args', None) or []
    if not args:
        return None   # zero-arg out-res: no measured lifting shape
    locs = scope[2] if scope is not None else None
    factory_names = set(getattr(gen, '_imported_generics', {}))
    # The module's OWN top-level structs: the user-iterator constructor
    # argument (`zip(TestIter(2, {2}), ...)` — part 4) resolves against
    # these and against nothing else, so a runtime-name collision in
    # `struct_field_types` cannot claim the shape.
    struct_names = {s.name for s in stmts if type(s).__name__ == 'StructDef'}
    conts = []
    for i, a in enumerate(args):
        c = iter_factory.resolve_container(a, factory_names, locs,
                                           struct_names)
        if c is None:
            work.refuse(
                f'{base}(...): argument {i} is not a statically resolvable '
                'local List / set / nested factory / iterator struct')
            return None
        if c['kind'] not in ('list', 'set', 'factory', 'struct'):
            work.refuse(
                f'{base}(...): {c["kind"]}-container argument — the out-res '
                'reconstruction builds List/Set/nested-factory/struct inners '
                'only')
            return None
        conts.append(c)
    # The CALL's pass mode: ANY moved argument (an rvalue a ref parameter
    # cannot bind) selects the owned overload — every list/set argument's
    # inner is then the owned one. A fully-borrowable call takes the
    # borrowed one. A bare local answers moved=True (the container
    # resolver's by-value convention — the owned inner holds the container
    # pointer and serves both spellings at this representation), so the
    # measured files' calls land owned; the nested-wrapper argument's
    # pointer is the inner in BOTH modes, so a mixed argument list
    # (wrapper local + bare list locals) simply takes the owned inners.
    moved = any(c['moved'] for c in conts)
    pr = _factory_return_out_for(fsrc, home, base, moved)
    if pr is None:
        work.refuse(f'{base}(...): no out-parameter overload with a '
                    'dependent wrapper')
        return None
    wrapper = pr['pr']['wrapper']
    hp = _wrapper_header_params(fsrc, wrapper)
    if hp is None:
        work.refuse(f'{base}(...): wrapper {wrapper!r} type-parameter '
                    'header unreadable in its home module')
        return None
    varparams = [p for p in hp if p[0].startswith('*')]
    if len(varparams) != 1:
        work.refuse(
            f'{base}(...): wrapper {wrapper!r} has {len(varparams)} '
            'variadic type parameters; the out-res subpath binds exactly one')
        return None
    varparam, varann = varparams[0]
    if varann.split()[0] != 'Iterator':
        work.refuse(
            f'{base}(...): wrapper {wrapper!r}'
            f' variadic parameter {varparam!r} is not `Iterator`-annotated')
        return None
    # One inner per container argument, exactly the return-value subpath's
    # derivation (list/set: the container's own iterator-type member;
    # factory: the nested factory's wrapper — the recursion below files it).
    inners = []   # (mention, mangled, elem_mention, inner_base, inner_args)
    for c in conts:
        if c['kind'] in ('list', 'set'):
            _ctname = 'List' if c['kind'] == 'set' else c['tname']
            chome, csrc = _container_home(gen, _ctname)
            if not csrc:
                work.refuse(
                    f'{base}(...): no module declares container '
                    f'{_ctname!r}')
                return None
            kind = 'owned' if moved else 'borrowed'
            rhs = iter_factory.iter_type_rhs(csrc, _ctname, kind)
            if rhs is None:
                work.refuse(f'{base}(...): {_ctname}.Iterator'
                            f'{"Owned" if kind == "owned" else ""}Type '
                            'member not found')
                return None
            inner_base = rhs.split('[', 1)[0].strip()
            inner = iter_factory.expand_inner(csrc, inner_base, rhs, c['elem'],
                                              bool(moved))
            if inner is None:
                work.refuse(f'{base}(...): {inner_base} type arguments do '
                            f'not bind for {_ctname}')
                return None
            inners.append((inner_base + '[' + ', '.join(inner['args']) + ']',
                           mm.mangle(inner_base,
                                     dict(zip(inner['names'], inner['args']))),
                           c['elem'], inner_base, tuple(inner['args'])))
            _register_named(gen, chome, [inner_base])
        elif c['kind'] == 'struct':
            # A USER-DEFINED iterator struct (measured 2026-10-21 part 4:
            # test_zip_bounds's `zip(TestIter(2, {2}), TestIter(2, {2}))`):
            # the struct ITSELF is the inner (its `comptime
            # IteratorType[...] = Self`), the constructor rvalue lowers to
            # the `<Struct> *` the wrapper's `_values[i]` holds, and
            # `__next__`/`bounds` dispatch on the struct's own in-TU
            # methods (the module-qualified csyms the next()/method-call
            # paths compose). Its element is the struct's `comptime
            # Element` — the wrapper's Element derivation needs a plain
            # scalar name. `inner_base`/`inner_args` are None: an in-TU
            # struct is emitted as part of THIS module (a top-level
            # statement), so there is no separate root to enqueue.
            _sd = next((s for s in stmts
                        if type(s).__name__ == 'StructDef'
                        and s.name == c['sname']), None)
            if _sd is None:
                work.refuse(
                    f'{base}(...): struct {c["sname"]!r} is not a top-level '
                    'struct of this module')
                return None
            _ea = getattr(_sd, 'comptime_aliases', {}).get('Element')
            _selem = getattr(_ea, 'name', None)
            if not (isinstance(_selem, str)
                    and re.match(r'^\w+$', _selem or '')):
                work.refuse(
                    f'{base}(...): struct {c["sname"]!r} has no plain-scalar '
                    f'`comptime Element = <name>` (got {_selem!r}) — the '
                    'out-res Element derivation needs one')
                return None
            inners.append((c['sname'], c['sname'], _selem, None, None))
        else:   # nested factory: its wrapper is the inner (its own
                # `comptime IteratorType[...] = Self`); the recursion below
                # files the nested record and enqueues its wrapper root.
            sub = _seed_one_factory(gen, work, mm, c['name'], c['node'],
                                    scope, stmts, import_map, queue, records,
                                    depth + 1)
            if sub is None:
                return None
            _selem = sub.get('elem')
            if not (isinstance(_selem, str)
                    and re.match(r'^\w+$', _selem or '')):
                work.refuse(
                    f'{base}(...): nested factory {c["name"]}\'s element is '
                    f'{_selem!r} — the out-res Element derivation needs a '
                    'plain scalar element (a nested tuple-element factory '
                    'is unmeasured)')
                return None
            inners.append((sub['wrapper_mangled'], sub['wrapper_mangled'],
                           _selem, None, None))
    # The wrapper's type arguments in DECLARATION order (bind_type_args
    # zips them positionally; the variadic parameter consumes every inner).
    _targs = {}
    for pname, pann in hp:
        if pname.startswith('*'):
            _targs[pname] = [i[0] for i in inners]
        else:
            # A VALUE parameter (zip's `origin: Origin`): the wrapper body
            # never reads it (measured — the spliced body references no
            # `origin`; it is threaded into the where-clause, which the
            # struct emitter drops), so its annotation's first word is a
            # sufficient, honest binding token.
            _w = pann.split()[0]
            if not re.match(r'^\w+$', _w):
                work.refuse(
                    f'{base}(...): wrapper {wrapper!r} value parameter '
                    f'{pname!r} annotation {pann!r} is not a plain type')
                return None
            _targs[pname] = _w
    wrapper_mangled = mm.mangle(wrapper, _targs)
    _register_named(gen, home, [wrapper])
    # The seed-only splice knowledge (part 4): each inner's ELEMENT mention
    # (`_sub_variadic`'s `<inner>.Element` -> element pass) and the wrapper's
    # own Element — chain's is the FIRST inner's element
    # (`Self.Element = Self.Ts[0].Element`); zip's is the tuple of them
    # (the explicit `self_element` override — zip's `Element` definition
    # spans lines, and the single-line member capture would splice a
    # dangling `Tuple[` into every `Self.Element` use).
    _elems = [i[2] for i in inners]
    _self_elem = ('Tuple[' + ', '.join(_elems) + ']'
                  if wrapper.lower().startswith('_zip') else _elems[0])
    _pos = []
    for pname, _pann in hp:
        if pname.startswith('*'):
            _pos.extend(_targs[pname])
        else:
            _pos.append(_targs[pname])
    work.variadic_meta[(wrapper, tuple(_pos))] = {
        'element_map': {i[0]: i[2] for i in inners},
        'self_element': _self_elem}
    # The wrapper's FIELD the factory body fills, and its cursor field
    # (`res._idx = 0` — chain has one, zip's body writes only `_values`):
    # both read from the wrapper TEMPLATE (not the whole home module —
    # the module holds dozens of `var ...: Int` fields), so a renamed
    # stdlib field is a refusal, not a guess.
    import elaborate
    _wsrc = elaborate.extract_struct_source(fsrc, wrapper) or ''
    _m = re.search(r'comptime (\w+) = Tuple\[\*Self\.\w+\]', _wsrc)
    _tuple_field = None
    if _m:
        _mf = re.search(r'var (\w+): Self\.' + re.escape(_m.group(1)) + r'\b',
                        _wsrc)
        _tuple_field = _mf.group(1) if _mf else None
    _idx_fields = re.findall(r'^\s*var (\w+): Int[ \t]*(?:$|#)',
                             _wsrc, re.M)
    _idx_field = _idx_fields[0] if len(_idx_fields) == 1 else None
    if _tuple_field is None:
        work.refuse(
            f'{base}(...): wrapper {wrapper!r} has no `var <f>: '
            'Self.<Tuple-of-inners member>` field — the out-res '
            'reconstruction cannot name the field it fills')
        return None
    rec = {'name': base, 'wrapper': wrapper,
           'wrapper_mangled': wrapper_mangled, 'kind': 'out-res',
           'moved': bool(moved),
           'out_param': pr['pr']['out_param'],
           # The wrapper's own Element (a NESTED out-res factory's record
           # answers the OUTER factory's Element derivation — chain's
           # Element is the FIRST inner's element; zip's Element is a
           # TUPLE, which the outer's scalar-element gate must refuse, so
           # None, not a wrong first element).
           'elem': (None if wrapper.lower().startswith('_zip')
                    else _elems[0]),
           'tuple_field': _tuple_field,
           'idx_field': _idx_field,
           'args': [
               {'kind': c['kind'],
                'inner_mangled': i[1],
                'elem_ctype': (iter_factory._MOJO_ELEM_C.get(
                    c.get('elem'), 'int64_t')
                    if c['kind'] in ('list', 'set') else None)}
               for c, i in zip(conts, inners)]}
    records[iter_factory.factory_call_key(base, node)] = rec
    work.enqueue(('struct', wrapper, tuple(_pos)), 0, queue)
    # Every inner must exist with a lowered `__next__` (the wrapper body
    # calls `next()` on each of them): list/set inners are enqueued as
    # their own roots exactly as the bare-`iter` branch does; nested-
    # factory inners are already roots through the recursion above.
    _seen_in = set()
    for c, i in zip(conts, inners):
        if c['kind'] in ('list', 'set') and i[3] is not None \
                and i[1] not in _seen_in:
            _seen_in.add(i[1])
            work.enqueue(('struct', i[3], i[4]), 0, queue)
    return rec


def _seed_direct_factory(gen, work, mm, base, node, fsrc, home, queue, records):
    """The zero-argument / direct-struct-return factory subpath
    (measured 2026-10-21: `count()` -> `_CountIterator` in std/itertools/
    itertools.mojo). The return annotation names a CONCRETE (non-generic)
    struct that IS the return value — no container, no inner: the factory
    body is `return {start, step}`, a fieldwise construction of the wrapper
    from the factory's own parameters (with their defaults in place).

    Deliberately narrow; every check is measured, not guessed:
      * exactly ONE 'direct' overload of `base` in the home module (two or
        more -> ambiguous, refuse; none -> this call is not a factory and
        returns None, the pre-subpath behavior);
      * the wrapper is declared `struct <name>(...):` in the home source —
        a `[` would make it generic, which is out of scope (its
        instantiating TU materializes the mangled copy through the
        existing path, and the generic head is what
        `monomorphize_source`'s substitution engine requires);
      * the wrapper's FIELD names, in declaration order, equal the
        factory's PARAMETER names, in order (count: start,step ==
        start,step) — that is precisely what makes the call's positional
        args map 1:1 onto the synthesized fieldwise `__init__`, with the
        factory's own parameter defaults (captured in the record as the
        parsed literals) filling the gaps.
    """
    import elaborate
    cands = [c for c in _factory_returns(fsrc, home, base)
             if c['pr'].get('kind') == 'direct']
    if len(cands) > 1:
        work.refuse(f'{base}(): multiple direct-struct overloads — '
                    'no unambiguous choice')
        return None
    if not cands:
        return None
    pr = cands[0]
    wrapper = pr['pr']['wrapper']
    if re.search(r'struct\s+' + re.escape(wrapper) + r'\s*\[', fsrc):
        work.refuse(f'{base}(): wrapper {wrapper!r} is generic in its home '
                    'module — the direct subpath handles concrete structs '
                    'only')
        return None
    if not re.search(r'struct\s+' + re.escape(wrapper) + r'\s*\(', fsrc):
        work.refuse(f'{base}(): return {wrapper!r} is not a concrete struct '
                    'in its home module')
        return None
    tmpl = elaborate.extract_struct_source(fsrc, wrapper)
    if tmpl is None:
        work.refuse(f'{base}(): no struct block for {wrapper!r} in its '
                    'home module')
        return None
    _sd = None
    for _s in Parser(py_tokenize(tmpl)).parse_module():
        if isinstance(_s, StructDef) and getattr(_s, 'name', None) == wrapper:
            _sd = _s
            break
    if _sd is None:
        work.refuse(f'{base}(): {wrapper!r} did not parse back as a struct '
                    f'in its home module')
        return None
    flds = [getattr(f, 'name', None)
            for f in (getattr(_sd, 'fields', None) or [])]
    pnames = pr['params']
    if flds != pnames:
        work.refuse(f'{base}(): wrapper field order {flds} != factory '
                    f'parameter order {pnames} — no unambiguous '
                    'constructor mapping')
        return None
    rec = {'name': base, 'wrapper': wrapper, 'wrapper_param': None,
           'wrapper_mangled': mm.mangle(wrapper, {}),
           'inner_mangled': None, 'inner_mention': None,
           'kind': 'direct', 'elem': None, 'elem_ctype': 'int64_t',
           'moved': False, 'wrapper_kwarg': None,
           'param_names': pnames, 'param_defaults': pr['defaults']}
    records[iter_factory.factory_call_key(base, node)] = rec
    # Register directly rather than via `_register_named`: that helper is
    # scoped to GENERIC template heads — its regex `[\[:]` matches
    # `struct NAME[` (a type-parameter block) and `struct NAME:` (a bare
    # concrete) but not `struct NAME(...)` (a concrete struct WITH bases),
    # which is exactly the shape this subpath handles (proven above by the
    # `struct <name>(` check). Same write, minus the regex, on a name this
    # function has already verified. The struct_field_types guard mirrors
    # `_register_named`'s own: a TU-local struct of the same name is
    # registered by the ordinary path, and splicing the home copy on top of
    # it would duplicate the StructDef.
    if wrapper not in gen.struct_field_types:
        gen._imported_generic_structs.setdefault(wrapper, home)
    work.enqueue(('struct', wrapper, ()), 0, queue)
    return rec


def _seed_direct_ctor(gen, work, mm, base, node, fsrc, home, scope, stmts,
                      import_map, queue, records):
    """The DIRECT-WRAPPER-CONSTRUCTOR subpath (part 6 family D, 2026-10-23,
    measured on test_product's test_product2_copies):

        var _product_iter = _Product2(
            TestCopyIterator(copy_a), TestCopyIterator(copy_b))

    a bare constructor call to an imported generic struct whose type
    arguments are the call's own ARGUMENT TYPES — no dependent-return factory
    in between, so no `_factory_returns` record exists, and the old path
    names the bare template symbol (the `extern int64_t _Product2 (...);`
    link hazard the syntax gate cannot see). Deliberately narrow; every check
    is measured, not guessed:

      * the base is a generic struct in its home module (the caller verified
        the home is another module than the caller's and `fsrc` is its
        source);
      * no keyword arguments (a `*`-only or defaulted-kwarg constructor
        cannot be bound from this pass's positional reading);
      * the value-argument arity EQUALS the type-parameter arity (the
        wrapper's `__init__` takes one value per inner, and the type
        arguments are exactly those inners' types);
      * every argument resolves to a LOCAL-struct mention (a local
        struct-constructor rvalue, or a local var annotated with a local
        struct) — the only argument type this codegen can spell in the
        mangled name AND define in this TU.

    The record is filed `kind='direct'` on the SAME key the emit side
    computes (`iter_factory.factory_call_key`): `_lower_factory_call`'s
    direct branch reconstructs exactly the constructor — alloc + the in-TU
    `__init__` (the same `_lower_struct_constructor` the factory records
    use), positional args in call order. The materialization itself rides
    the queue, so pre-registration, the annotation/callee rewrites and the
    inner walk all run on it unchanged."""
    import elaborate
    if not isinstance(node.func, IdentExpr):
        # The bracketed spelling (`_Product2[X, Y](...)`) names its type
        # arguments explicitly — the ROOT seed and `_rewrite_callees` own
        # that shape (their `_concrete_args` reads the brackets); this
        # subpath is the BARE spelling only (measured).
        work.refuse(f'{base}(...): the direct-ctor subpath takes the bare '
                    'spelling only')
        return None
    tmpl = elaborate.extract_struct_source(fsrc, base)
    if tmpl is None:
        work.refuse(f'{base}(...): no struct template in its home module')
        return None
    tparams = elaborate.type_param_names(tmpl)
    if not tparams:
        work.refuse(f'{base}(...): {base!r} is not generic in its home module')
        return None
    args_nodes = getattr(node, 'args', None) or []
    if getattr(node, 'kwargs', None):
        work.refuse(f'{base}(...): a keyword argument is not a positional '
                    'type argument')
        return None
    if len(args_nodes) != len(tparams):
        work.refuse(f'{base}(...): {len(args_nodes)} value args for '
                    f'{len(tparams)} type parameters')
        return None
    locs = scope[2] if scope is not None else None
    struct_names = {st.name for st in (stmts or ())
                    if type(st).__name__ == 'StructDef'}
    targs = []
    for a in args_nodes:
        m = _direct_ctor_arg_mention(a, struct_names, locs)
        if m is None:
            work.refuse(f'{base}(...): an argument has no statically '
                        'resolvable local-struct type')
            return None
        targs.append(m)
    # The constructor parameter names, in order — the record's positional
    # map (the emit side's direct branch walks them against node.args).
    # Read from the template's `__init__` overload whose arity matches;
    # they are scaffolding for the reconstruction — the REAL overload
    # resolution happens in `_lower_struct_constructor` at emit time.
    pnames = None
    try:
        for s in Parser(py_tokenize(tmpl)).parse_module():
            if not isinstance(s, StructDef) \
                    or getattr(s, 'name', None) != base:
                continue
            for mth in (getattr(s, 'methods', None) or []):
                if getattr(mth, 'name', None) != '__init__':
                    continue
                mp = getattr(mth, 'params', None) or []
                if len(mp) == len(args_nodes) + 1:
                    pnames = [p[0] for p in mp[1:]]
                    break
            if pnames is not None:
                break
    except Exception:
        pnames = None
    if pnames is None:
        pnames = [f'_direct_arg_{i}' for i in range(len(args_nodes))]
    wrapper_mangled = mm.mangle(base, dict(zip(tparams, targs)))
    _register_named(gen, home, [base])
    records[iter_factory.factory_call_key(base, node)] = {
        'name': base, 'wrapper': base, 'wrapper_param': None,
        'wrapper_mangled': wrapper_mangled, 'inner_mangled': None,
        'inner_mention': None, 'kind': 'direct', 'elem': None,
        'elem_ctype': 'int64_t', 'moved': False, 'wrapper_kwarg': None,
        'param_names': pnames, 'param_defaults': {}}
    work.enqueue(('struct', base, tuple(targs)), 0, queue)
    return wrapper_mangled


def _seed_factories(gen, work, stmts, queue):
    """Entry: find every factory call, evaluate it, register + enqueue its
    wrapper, and file the record the emit side reconstructs from. Lazy-imports
    `monomorphize` (which imports `gimple_codegen` at module level — the cycle
    this pass is loaded in the middle of)."""
    import monomorphize as mm
    records = gen._intu_factory_records
    import_map = _import_name_map(stmts)

    def visit(node, scope):
        base = (node.func.obj.name if isinstance(node.func, SubscriptExpr)
                and isinstance(node.func.obj, IdentExpr)
                else node.func.name if isinstance(node.func, IdentExpr)
                else None)
        if not base:
            return
        _seed_one_factory(gen, work, mm, base, node, scope, stmts, import_map,
                          queue, records)
    _walk_scoped(stmts, visit)


def _sites_of(parsed):
    """Every annotation STRING in a parsed concrete module, as `(owner, attr)`
    handles, so the rewrite can write back to the node.

    The rewrite is not optional: an annotation left as raw `Base[Args]` text is
    a name this codegen has never heard of, so the field or return type falls
    back to `int64_t` — a boxed integer where a struct pointer belongs, which
    is exactly the `next(<struct>)`-has-no-receiver-type failure this module
    exists to remove."""
    sites = []
    for s in parsed:
        if isinstance(s, FunctionDef):
            sites += [(s.params, i) for i, (_p, ann) in enumerate(s.params)
                      if isinstance(ann, str) and ann]
            if isinstance(s.return_type, str) and s.return_type:
                sites.append((s, 'return_type'))
        elif isinstance(s, StructDef):
            sites += [(f, 'type_ann') for f in (getattr(s, 'fields', None) or [])
                      if isinstance(getattr(f, 'type_ann', None), str)
                      and f.type_ann]
            for m in (getattr(s, 'methods', None) or []):
                sites += [(m.params, i) for i, (_p, ann) in enumerate(m.params)
                          if isinstance(ann, str) and ann]
                if isinstance(getattr(m, 'return_type', None), str) and m.return_type:
                    sites.append((m, 'return_type'))
    return sites


def _collect_inner(work, rec, queue):
    """What a materialized concrete source asks for next: the generic structs
    its annotations mention, and the generic calls its bodies make.

    `rec['src_path']` is the file the concrete source was extracted FROM, and
    it is what makes a struct that no `from ... import` line ever names
    discoverable. `from std.iter import empty` registers the generic FUNCTION
    `empty` and nothing else; `_Empty` is named only by `empty`'s own RETURN
    annotation, never by the importer's import line — which is exactly why
    `_register_generic_structs_named` exists for the demand-driven route, and
    why this pass has to do the same registration before it can look the name
    up. Without it `empty[Int]()` materializes and its `_Empty[T]` return
    annotation erases to `int64_t`, which is the boxed-integer shape
    `next(<struct>)` cannot dispatch on."""
    gen = work.gen
    depth = work.depth.get((rec['kind'], rec['base'], rec['args']), 0)
    if depth >= _MAX_DEPTH:
        return
    ann_sites = rec['sites']
    bases = []
    for holder, attr in ann_sites:
        ann = _get(holder, attr)
        for base, args, _s, _e in _mentions(ann or ''):
            if base in _IN_TU_LIST_BASES:
                continue
            if base not in bases:
                bases.append(base)
    if bases:
        _register_named(gen, rec['src_path'], bases)
    for holder, attr in ann_sites:
        ann = _get(holder, attr)
        for base, args, _s, _e in _mentions(ann or ''):
            if base in _IN_TU_LIST_BASES:
                continue
            # UNCONDITIONAL, unlike a root. Once an instantiation is being
            # materialized, every generic struct its annotations name must be a
            # REAL struct too: a field annotated `Optional[Int64]` whose type
            # erased to `int64_t` is a boxed integer, which is the failure this
            # whole pass exists to remove.
            if (base in gen._imported_generic_structs and args
                    and all(_is_concrete(a) for a in args)):
                key = ('struct', base, tuple(args))
                work.enqueue(key, depth + 1, queue)

    def visit(n):
        if not isinstance(n, CallExpr):
            return
        base = (n.func.obj.name if isinstance(n.func, SubscriptExpr)
                and isinstance(n.func.obj, IdentExpr)
                else n.func.name if isinstance(n.func, IdentExpr) else None)
        if not base:
            return
        if base in _IN_TU_LIST_BASES:
            return
        # Same registration, for a struct CONSTRUCTED inside the concrete body
        # (`empty`'s body is `return _Empty[T]()`) — that call names the struct
        # as a callee, never in an annotation.
        _register_named(gen, rec['src_path'], [base])
        kind = _callee_kind(gen, base)
        if kind is None:
            return
        args = _concrete_args(work, kind, base, n)
        if args is None:
            return
        work.enqueue((kind, base, tuple(args)), depth + 1, queue)
    _walk(rec['parsed'], visit)


def _register_named(gen, src_path, names):
    """Register each of `names` that `src_path` declares as a `struct NAME[...]`
    template, in `_imported_generic_structs`. The one caller-side addition to
    `emit_resolve._register_generic_structs_named`, which this pass cannot use
    because that function's own `gen._imported_generic_structs`/`struct_field_
    types` guards assume it runs during CALL lowering rather than before any
    struct registration."""
    if not src_path:
        return
    todo = [n for n in names
            if n and n not in gen._imported_generic_structs
            and n not in gen.struct_field_types]
    if not todo:
        return
    try:
        text = open(src_path).read()
    except OSError:
        return
    for n in todo:
        if re.search(rf'\bstruct\s+{re.escape(n)}\s*[\[:]', text):
            gen._imported_generic_structs.setdefault(n, src_path)


def _rewrite_inner_bodies(work, base, concrete):
    """Rewrite the spliced stdlib bodies of the in-TU iterators (the two
    List iterators + the take/drop wrappers — see _IN_TU_ITER_BODIES) to
    lowerable expressions. Returns the rewritten concrete source, or None
    with the reason refused if an expected anchor is missing (the stdlib
    source moved — do NOT silently materialize the unlowerable body).

    Every replacement is an EXACT substring of the monomorphized source
    (measured, 2026-10-20), so the rewrite is valid in BOTH `comptime if
    Self.forward` branches of `_ListIter.__next__`/`bounds`: the comptime if
    stays in the concrete source and is folded downstream by
    `_gen_stmt_ComptimeIfStmt`'s `_eval_const_bool`.

    The replacements, and the lowering each one lands on:
      _ListIter.__next__  `self._data[unsafe_offset=<i>]`  ->  `self._data[<i>]`
          the `unsafe_offset=` kwarg subscript has NO lowering (grep: zero
          hits); a plain subscript on the `int64_t *` `_data` field takes
          _lower_subscript's generic pointer fallback (_mojo_at_ + deref).
      _ListIterOwned.__next__  `self._list.unsafe_ptr().unsafe_offset(<i>)
          .unsafe_take_pointee()`  ->  `self._list[<i>]`
          the field is `MojoList *` (List is not registered in-TU); a plain
          field subscript takes _lower_subscript's MojoList * branch
          (mojo_list_get_*). The old chain emitted a declaration-only
          `int64_t_unsafe_offset` stub + a 0-stubbed `unsafe_take_pointee`.
      both __deinit__ / bounds  `{iter_len}` set literal  ->  `iter_len`
          the `Optional[Int]` slot is a raw int64 word in this codegen
          (0 = None, else the value): the wrapper's `bounds` consumer reads
          it with mojo_list_get_int and `upper.value()` lowers to identity.
          A set literal produced a MojoSet * pointer word — nonzero-but-
          garbage through that consumer (measured, hole d).
      _ListIterOwned.__deinit__  body  ->  `pass`
          the remaining-element Span span-destroy (`Span(...)._
          unchecked_subspan(...).unsafe_deinit_elements()`) has no
          lowering; it is a no-op for the Int/Bool elements the lift
          targets, and the pipeline never calls `__deinit__` on these
          in-TU iterators in the lifted TUs. Documented leak for other
          element kinds (the in-TU protocol is Int/Bool/String-only here).
    """
    pairs = {
        '_ListIter': (
            ('self._data[unsafe_offset=self._index - 1]',
             'self._data[self._index - 1]'),
            ('self._data[unsafe_offset=self._index]',
             'self._data[self._index]'),
            ('return (iter_len, {iter_len})',
             'return (iter_len, iter_len)'),
        ),
        '_ListIterOwned': (
            ('    def __deinit__(deinit self):\n'
             '        # Destroy the remaining elements that have not yet been\n'
             '        # iterated over.\n'
             '        Span(self._list)._unchecked_subspan(\n'
             '            start=self._index, end=len(self._list)\n'
             '        ).unsafe_deinit_elements()\n'
             '        self._list._len = 0',
             '    def __deinit__(deinit self):\n'
             '        pass'),
            ('        return (\n'
             '            self._list.unsafe_ptr()\n'
             '            .unsafe_offset(self._index - 1)\n'
             '            .unsafe_take_pointee()\n'
             '        )',
             '        return self._list[self._index - 1]'),
            ('return (iter_len, {iter_len})',
             'return (iter_len, iter_len)'),
        ),
        '_TakeIterator': (
            # bounds: the inner's upper slot is a raw word (Some = the
            # value, and the source's `{iter_len}` producer is a 1-element
            # set = always Some) — `if upper:` lowers to int-truthiness of
            # the value and misbranches at 0 (measured, test_take_bounds
            # it4). The branches are value-identical in every lifted
            # shape, so fold them.
            ('        if upper:\n'
             '            return (lower, min(upper.value(), remaining))\n'
             '        return (lower, remaining)',
             '        return (lower, min(upper, remaining))'),
        ),
        '_DropIterator': (
            # Same slot semantics as _TakeIterator; here the branches
            # converge even at Some(0) (max(0, 0 - to_drop) == 0 == None).
            ('        if upper:\n'
             '            return (lower, max(0, upper.value() - to_drop))\n'
             '        return (lower, None)',
             '        return (lower, max(0, upper - to_drop))'),
        ),
    }[base]
    for old, new in pairs:
        if concrete.count(old) != 1:
            work.refuse(f'{base}: body rewrite anchor missing or ambiguous '
                        f'({concrete.count(old)} hit(s)) for {old[:40]!r}...')
            return None
        concrete = concrete.replace(old, new)
    return concrete


def _materialize(work, key):
    """One instantiation. Returns a record dict, or None with the reason
    recorded. Every failure is a REFUSAL: nothing is emitted and the `.o` route
    is left to run unchanged."""
    import elaborate
    import monomorphize as mm
    kind, base, args = key
    module_src = _module_src(work.gen, base, kind)
    if module_src is None:
        work.refuse(f'no source for {base!r}')
        return None
    tmpl = (elaborate.extract_fn_source(module_src, base) if kind == 'fn'
            else elaborate.extract_struct_source(module_src, base))
    src_path = (work.gen._imported_generic_structs if kind == 'struct'
                else work.gen._imported_generics).get(base)
    if not tmpl:
        work.refuse(f'no {kind} template for {base!r}')
        return None
    if kind == 'struct' and not elaborate.type_param_names(tmpl):
        # A CONCRETE (non-generic) struct — the direct-struct factory
        # subpath (`count()` -> `_CountIterator`, measured 2026-10-21):
        # there is no bracket block to bind, and
        # `monomorphize_source`'s head match (its substitution engine)
        # requires one — it refused the concrete template with ValueError
        # "no generic `fn`/`struct name[...]` found" (measured). So the
        # template IS the concrete source and the mangled name is the
        # plain name (`mangle`'s own zero-arg contract: returned
        # unchanged). Gated on `kind == 'struct'` on purpose: the fn roots
        # are all generic (the `_imported_generics` registry only holds
        # imported generic functions), and a concrete fn, should one ever
        # queue, keeps its pre-subpath honest refusal.
        mangled, concrete = base, tmpl
        targs = {}
    else:
        targs = elaborate.bind_type_args(tmpl, list(args))
        if targs is None:
            work.refuse(f'{base}[{", ".join(args)}]: a bracket parameter is unbound')
            return None
        # A VARIADIC binding (part 4: the chain/zip out-res wrapper's `*Ts`
        # consumes every inner) takes `monomorphize_source`'s dedicated
        # pass; its seed-only splice knowledge (each inner's element
        # mention, the wrapper's own Element) rides in work.variadic_meta,
        # keyed by (wrapper, positional-args) — the same key the seed used
        # to enqueue this instantiation.
        _vmeta = None
        if any(isinstance(v, (list, tuple)) for v in targs.values()):
            _vmeta = work.variadic_meta.get((base, tuple(args)))
            if _vmeta is None:
                work.refuse(
                    f'{base}[{", ".join(args)}]: variadic instantiation '
                    'with no seed-filed splice metadata')
                return None
        try:
            mangled, concrete = mm.monomorphize_source(
                tmpl, targs,
                element_map=(_vmeta or {}).get('element_map'),
                self_element=(_vmeta or {}).get('self_element'))
        except Exception as e:
            work.refuse(f'{base}[{", ".join(args)}]: {type(e).__name__}: {e}')
            return None
    if kind == 'struct' and base in _IN_TU_ITER_BODIES:
        concrete = _rewrite_inner_bodies(work, base, concrete)
        if concrete is None:
            return None
    try:
        parsed = Parser(py_tokenize(concrete)).parse_module()
    except Exception as e:
        work.refuse(f'{base}[{", ".join(args)}]: parse: {type(e).__name__}: {e}')
        return None
    return {'kind': kind, 'base': base, 'args': tuple(args), 'targs': targs,
            'mangled': mangled, 'parsed': parsed, 'sites': _sites_of(parsed),
            'src_path': src_path, 'src': concrete}


# ── the entry point ────────────────────────────────────────────────────────

def run(gen, stmts):
    """Materialize in-TU instantiations for `stmts`; returns the extra
    top-level statements to append to them, and fills `gen._intu_funcs` /
    `_intu_structs` (what this compile DEFINES) and `gen._intu_func_args` /
    `_intu_struct_args` (what the `.o` route must NOT also emit)."""
    for attr, default in (('_intu_funcs', {}), ('_intu_structs', {}),
                          ('_intu_func_args', {}), ('_intu_struct_args', {}),
                          ('_intu_factory_records', {})):
        if not hasattr(gen, attr):
            setattr(gen, attr, dict(default))
    if _skip(gen):
        return []
    work = _Work(gen)
    queue = []
    # Dependent-return iterator factories (`peekable(l)`, `take(l, 3)`, ...):
    # evaluate the return dependency and enqueue the wrapper roots BEFORE the
    # generic seed, so the wrapper and (via `_collect_inner`) its inner
    # iterator are materialized in the same closure as everything else.
    _seed_factories(gen, work, stmts, queue)

    def seed(n):
        """ROOTS. A struct root is one the `.o` route provably cannot register
        (a duplicated method name outside the iteration protocol); a function root
        is one whose return annotation names such a struct
        (`_fn_returns_unbuildable_struct`). Nothing else is a root, and the
        distinction is measured rather than guessed — see
        `_protocol_only_overloads`'s own table for what widening it costs."""
        if not isinstance(n, CallExpr):
            return
        base = (n.func.obj.name if isinstance(n.func, SubscriptExpr)
                and isinstance(n.func.obj, IdentExpr)
                else n.func.name if isinstance(n.func, IdentExpr) else None)
        if not base:
            return
        kind = _callee_kind(gen, base)
        if kind is None:
            return
        if kind == 'struct':
            if not _protocol_only_overloads(gen, base):
                return
        elif not _fn_returns_unbuildable_struct(work, base):
            return
        args = _concrete_args(work, kind, base, n)
        if args is None:
            return
        work.enqueue((kind, base, tuple(args)), 0, queue)
    _walk(stmts, seed)
    if not queue:
        return []

    seen = set()
    while queue:
        if len(work.extra) >= _MAX_INSTANTIATIONS:
            work.refuse('instantiation closure exceeded its work bound')
            break
        key = queue.pop(0)
        if key in seen:
            continue
        seen.add(key)
        rec = _materialize(work, key)
        if rec is None:
            continue
        work.alias[key] = rec['mangled']
        existing = work.records.get(rec['mangled'])
        if existing is not None:
            # Two different SPELLINGS of one instantiation — `Coord[
            # ComptimeInt[5], Coord[Int32, ComptimeInt[3]], Int64]` and
            # `Coord[ComptimeInt[5], Int32, ComptimeInt[3], Int64]` both bind
            # the same values and therefore mangle identically. They are ONE
            # instantiation and must produce ONE node; emitting both gave gcc
            # `error: redefinition of 'Coord_...___init___0120be'` on two
            # different source lines of test/utils/test_coord.mojo. The
            # MANGLED NAME is the identity, which is the whole reason it is
            # injective.
            continue
        work.records[rec['mangled']] = rec
        work.extra.extend(rec['parsed'])
        gen._extra_no_mangle.add(rec['mangled'])
        if rec['kind'] == 'fn':
            gen._intu_funcs[rec['mangled']] = {'base': rec['base'], 'targs': rec['targs']}
            gen._intu_func_args[(rec['base'], rec['args'])] = rec['mangled']
        else:
            gen._intu_structs[rec['mangled']] = {'base': rec['base'], 'targs': rec['targs']}
            gen._intu_struct_args[(rec['base'], rec['args'])] = rec['mangled']
        _collect_inner(work, rec, queue)
    # Pre-register every materialized struct's MANGLED NAME in
    # gen.struct_field_types (empty field map) BEFORE the statement loop and
    # the signature passes run. A mangled-name annotation — the form
    # `_rewrite_annotations` leaves behind (`var _inner: _ListIter_1_T_3_Int_...`,
    # and the `__init__(var inner: ...)` param that reads the same text) —
    # resolves through `ann in gen.struct_field_types`, which only becomes
    # true once the struct's OWN statement has run. But the wrapper's
    # `__init__` signature is computed BEFORE that: Pass 2b-bis and the
    # call site's overload resolution both land in the pre-statement passes,
    # and there the annotation erases to int64_t — the box — while the
    # DEFINITION (emitted later, when the inner's statement has registered
    # its fields) answers `<inner> *`. The two halves of the symbol then
    # disagree and gcc fails the call site with
    # "makes integer from pointer without a cast". An empty field map is
    # enough: every reader of a registered name answers `name *` (the
    # universal struct-as-pointer convention) or falls back on the field
    # lookups that the struct's own statement fills in later, and no pass
    # treats "registered but no fields yet" as a struct with zero fields —
    # the field-count readers guard on `len(...) > 0`.
    # Record the names this loop ADDS, in `gen._intu_prereg_structs`.
    # gen_module_impl's `_selfhost_hardcoded_struct_names` snapshot
    # (module_gen.py, taken after this pass runs at line ~3411 but before the
    # statement loop) treats EVERY pre-existing struct_field_types key as a
    # selfhost-hardcoded struct and SKIPS it in the read-field pass
    # (module_gen.py:5903) and the local-annotation pass (module_gen.py:6023).
    # Measured 2026-10-20: with the pre-registration in place, the in-TU
    # `_Empty_1_T_3_Int` (test/iter/test_empty.mojo) landed in that snapshot
    # and its `int64_t copy` field (minted by the read-field pass from
    # `self.copy()` in `__iter__(ref self)`) plus the whole reflection
    # dispatch (`_mojo_getattr_*`, the `_known[]` type-tag table, fieldnames,
    # repr) were dropped — `typedef {__mojo_type_id, int _dummy}` and
    # `_known[] = {0}` instead, a 2 KB C delta on test_empty and smaller ones
    # on test_once/test_repeat, all of them byte-diffed against the clean
    # master's C in fresh single-file processes. The exclusion set restores
    # the clean-master pass behavior for exactly the names this loop added,
    # while the early registration itself (what the pre-statement signature
    # passes need) stays in place.
    _prereg = getattr(gen, '_intu_prereg_structs', None)
    if _prereg is None:
        _prereg = set()
        gen._intu_prereg_structs = _prereg
    for rec in work.records.values():
        if rec['kind'] == 'struct':
            if rec['mangled'] not in gen.struct_field_types:
                gen.struct_field_types[rec['mangled']] = {}
                _prereg.add(rec['mangled'])
    _rewrite_annotations(work)
    _rewrite_callees(work, stmts)
    _rewrite_ctor_calls(work, stmts)
    _rewrite_intu_ctor_calls(work)
    _synthesize_inner_defaults(work, stmts)
    if work.notes:
        gen._intu_notes = work.notes
    return work.extra


def _skip(gen) -> bool:
    """Where this pass must not run.

    - `do_imports` compiles each imported module in its own nested `temp_gen`,
      so a definition spliced into the IMPORTER is invisible to the imported
      module's own body. The single-TU path (`do_imports=False`) is what
      `compile_stdlib.py`, `build_stdlib_dylib.py` and the whole `test/` tree
      use, and it is where the iterator family needs this.
    - The self-hosted bootstrap compiles this compiler's own `.py` sources,
      where `gen` has no `struct_field_types` view yet at this point in
      gen_module and a wrong instantiation is a stage1-vs-stage2 divergence
      rather than a per-module compile error."""
    if getattr(gen, 'do_imports', False):
        return True
    fn = str(getattr(gen, '_current_filename', '') or '')
    return os.path.basename(fn) in ('gimple_codegen.py',) or fn.endswith(
        os.path.join('mojo', 'backend_gimple', 'elab_intu.py'))


def _synthesize_inner_defaults(work, stmts):
    """A materialized wrapper's SPLICED body calls the inner's protocol
    methods; for a LOCAL inner struct (this module's own StructDef) that does
    not override one, the call must reach the TRAIT'S DEFAULT implementation.
    Unsynthesized, `self._inner_a.bounds()` in the spliced
    `_Product2[TestCopyIterator, TestCopyIterator].bounds()` auto-stubs to a
    forward declaration nothing defines (`TestCopyIterator_bounds` — a link
    failure the syntax gate cannot see), because the `Iterator` trait's
    default `bounds` (`std/iter/__init__.mojo`: `return (0, None)`) is
    compiled nowhere in a single-TU build.

    Synthesized as a real method on the local struct (a method, not a field
    — the layout is untouched): the emitter emits `bounds` exactly like the
    struct's own methods, and the spliced call resolves to it. Only the one
    measured method is synthesized (`bounds` — the one the product wrappers'
    spliced `bounds()` calls); every other protocol method a local inner
    lacks keeps its old path, to be measured when a test actually needs it.
    Idempotent per struct (a struct that overrides `bounds` is skipped)."""
    if not stmts:
        return
    struct_defs = {}
    for s in stmts:
        if type(s).__name__ == 'StructDef':
            struct_defs.setdefault(s.name, s)
    if not struct_defs:
        return
    for rec in work.records.values():
        if rec.get('kind') != 'struct':
            continue
        for a in rec.get('args') or ():
            sd = struct_defs.get(a)
            if sd is None:
                continue
            have = {getattr(m, 'name', None)
                    for m in (getattr(sd, 'methods', None) or [])}
            if 'bounds' in have:
                continue
            snippet = ('def bounds(self) -> Tuple[Int, Optional[Int]]:\n'
                       '    return (0, None)\n')
            try:
                parsed = Parser(py_tokenize(snippet)).parse_module()
            except Exception as e:
                work.refuse(f'{a}: the trait-default bounds snippet failed '
                            f'to parse: {type(e).__name__}: {e}')
                continue
            fn = None
            for s in parsed:
                if type(s).__name__ == 'FunctionDef' \
                        and getattr(s, 'name', None) == 'bounds':
                    fn = s
                    break
            if fn is None:
                work.refuse(f'{a}: the trait-default bounds snippet parsed '
                            'no function')
                continue
            sd.methods.append(fn)
            _walk_ast_invalidate(sd)


def _rewrite_annotations(work):
    # The NESTED-mention bridge (measured 2026-10-22, part 5, test_map): a
    # wrapper whose inner is itself a generic mention spells its field as
    # `var _inner: _ListIterOwned[CopyCounter[NoneType]]`. The rewrite runs
    # innermost-first, so after the inner round the OUTER mention's type
    # argument is the inner's MANGLED name while work.alias keys hold the
    # RAW mention the seed enqueued — the direct lookup misses and the outer
    # stays unrewritten, the field erases to int64_t, and the wrapper's
    # `__next__` body (`next(self._inner)`) is refused at definition time
    # (the "prototype only" degradation). Translate a mangled argument back
    # to the raw mention for the lookup; the innermost-first order and the
    # single-argument gate mean this fires exactly on that shape — a
    # mention whose argument was never rewritten is untouched.
    mangled_raw = {}
    for (kind, base, args), mangled in work.alias.items():
        if kind == 'struct':
            mangled_raw[mangled] = f"{base}[{', '.join(args)}]"
    for rec in work.records.values():
        for holder, attr in rec['sites']:
            ann = _get(holder, attr)
            if not isinstance(ann, str) or '[' not in ann:
                continue
            new = _rewrite_ann(work, ann, mangled_raw)
            if new != ann:
                _set(holder, attr, new)


def _rewrite_ann(work, ann, mangled_raw):
    """`ann` with every MATERIALIZED `Base[Args]` mention replaced. Bounded by
    the annotation's own bracket depth: each round that changes the string
    removes at least one bracket pair, so this cannot spin."""
    for _ in range(8):
        hit = None
        for base, args, start, end in _mentions(ann):
            mangled = work.alias.get(('struct', base, tuple(args)))
            if mangled is None and len(args) == 1:
                raw = mangled_raw.get(args[0])
                if raw is not None:
                    mangled = work.alias.get(('struct', base, (raw,)))
            if mangled:
                hit = (start, end, mangled)
                break
        if hit is None:
            return ann
        ann = ann[:hit[0]] + hit[2] + ann[hit[1]:]
    return ann


def _rewrite_callees(work, stmts):
    """Point every call site of a materialized generic at the concrete name.

    Both spellings need it. `Base[Args](...)` and bare `Base(...)` both route
    through `_elaborate_generic_struct_call` / `_elaborate_generic_call`, and
    those are SUPPRESSED for an instantiation this compile already defines (a
    second definition of the same symbol is precisely the `error: conflicting
    types for '<name>'` the reverted attempt produced). Without this rewrite the
    call would fall through to a bare `Base(...)` naming a template."""
    gen = work.gen

    def visit(n):
        if not isinstance(n, CallExpr):
            return
        base = (n.func.obj.name if isinstance(n.func, SubscriptExpr)
                and isinstance(n.func.obj, IdentExpr)
                else n.func.name if isinstance(n.func, IdentExpr) else None)
        if not base:
            return
        kind = _callee_kind(gen, base)
        if kind is None:
            return
        args = _concrete_args(work, kind, base, n)
        if args is None:
            return
        mangled = work.alias.get((kind, base, tuple(args)))
        if mangled:
            n.func = IdentExpr(name=mangled)
            _walk_ast_invalidate(n)
    _walk(stmts, visit)
    for rec in work.records.values():
        _walk(rec['parsed'], visit)


def _rewrite_ctor_calls(work, stmts):
    """Rewrite a module function's OWN bare `Base(args)` constructor call to
    the base's in-TU MANGLED name (part 5, 2026-10-22, measured on
    test_cycle/test_product: `def _owned3(...) -> _CopyableOwned[3]` whose
    body ends in `return _CopyableOwned(data^)`, a no-bracket spelling the
    argument-less inferer cannot solve — `size` is not inferable from a
    `MojoList *` argument, and the .o route's overload ambiguity refusal
    erases the call to a box).

    The rewrite hands the call to the CONCRETE-struct constructor dispatch
    (emit_calls' `_fname_ctor in gen.struct_field_types` arm, which the
    in-TU pre-registration above made true for the mangled name) — the
    in-TU `__init__` overload the seed's materialization registered.

    The instantiation is determined per call:
      * the base's SOLE in-TU instantiation binds every bare call to it;
      * with SEVERAL (test_cycle's `_CopyableOwned[1]` + `_CopyableOwned[3]`
        both materialized in one TU), the ENCLOSING function's own return
        annotation (`-> _CopyableOwned[3]`) names the instantiation — a
        call in a function whose return annotation does not name one of the
        base's in-TU instantiations is left alone (its old honest path
        stands).
    Bracketed spellings are NOT touched here: `_rewrite_callees` already
    rewrote the concrete ones, and a bracketed call whose arguments the
    inferer cannot solve is the .o route's business, not this pass'.
    """
    gen = work.gen
    by_base = {}
    for (kind, base, args), mangled in work.alias.items():
        if kind == 'struct':
            by_base.setdefault(base, {})[tuple(args)] = mangled
    if not by_base:
        return
    for st in stmts or ():
        if type(st).__name__ != 'FunctionDef':
            continue
        ret = getattr(st, 'return_type', None)
        ret_args = None
        if isinstance(ret, str):
            m = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*([^\]]+)\]\s*$',
                         ' '.join(ret.split()))
            if m:
                ret_args = (m.group(1),
                            tuple(a.strip() for a in m.group(2).split(',')))
        body = getattr(st, 'body', None) or ()

        def visit(n, _ret=ret_args):
            if type(n).__name__ != 'CallExpr':
                return
            f = getattr(n, 'func', None)
            if type(f).__name__ != 'IdentExpr':
                return
            insts = by_base.get(f.name)
            if not insts:
                return
            if len(insts) == 1:
                args = next(iter(insts))
            elif _ret and _ret[0] == f.name and _ret[1] in insts:
                args = _ret[1]
            else:
                return      # ambiguous: the old honest path stands
            n.func = IdentExpr(name=insts[args])
            _walk_ast_invalidate(n)
        _walk(list(body), visit)


def _rewrite_intu_ctor_calls(work):
    """The SAME rewrite, for the BODIES of in-TU materialized records
    (part 5, 2026-10-22, measured on test_cycle: the spliced
    `_CopyableOwned[3]` body's `__iter__` ends in
    `return _CopyableOwnedIter(self._data.copy(), 0)` — a bare call whose
    target's `size` is not inferable from a `MojoList *` argument either).

    Unrewritten, the call dispatches to the module's own TEMPLATE struct
    (the generic struct the test file defines, emitted as a concrete C
    struct with the type parameter as a runtime FIELD — a different layout
    than the mangled instantiation, and a `___init__` symbol the .o route
    never compiles): a link-time failure, or a silently wrong object.

    The enclosing record supplies the context the module-function pass gets
    from the return annotation: the record's MONOMORPHIZED source names the
    target's concrete instantiation in a bound mention (`comptime
    IteratorOwnedType: Iterator = _CopyableOwnedIter[3]` after the
    `Self.size -> 3` splice) — EXACTLY ONE distinct in-TU instantiation of
    the base is mentioned in the record's source, and that one binds every
    bare call to it; zero or several is a refusal to guess (the old path
    stands). The sole-instantiation shortcut needs no mention at all."""
    by_base = {}
    for (kind, base, args), mangled in work.alias.items():
        if kind == 'struct':
            by_base.setdefault(base, {})[tuple(args)] = mangled
    if not by_base:
        return
    for rec in work.records.values():
        if rec['kind'] != 'struct':
            continue
        src = rec.get('src') or ''
        if not src:
            continue

        def visit(n, _src=src):
            if type(n).__name__ != 'CallExpr':
                return
            f = getattr(n, 'func', None)
            if type(f).__name__ != 'IdentExpr':
                return
            insts = by_base.get(f.name)
            if not insts:
                return
            if len(insts) == 1:
                args = next(iter(insts))
            else:
                mentions = set()
                for m in re.finditer(
                        rf'\b{re.escape(f.name)}\s*\[\s*([^\]]+)\s*\]',
                        _src):
                    a = tuple(x.strip() for x in m.group(1).split(','))
                    if a in insts:
                        mentions.add(a)
                if len(mentions) != 1:
                    return      # ambiguous: the old honest path stands
                args = next(iter(mentions))
            f.name = insts[args]
            _walk_ast_invalidate(n)
        _walk(rec['parsed'], visit)
