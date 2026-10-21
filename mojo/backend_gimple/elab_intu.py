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
_IN_TU_LIST_BASES = ('List', 'list')

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


_BUILTIN_FACTORY_HOME = {'enumerate': 'std.iter', 'iter': 'std.iter'}


def _factory_home(gen, import_map, base):
    """The path of the module that DEFINES `def base`, or None. Generic
    factories (`def take[...](...)`) are already in `_imported_generics`; the
    non-generic overload (`def peekable(...)`) is not, so resolve it from the
    test's own import line, following re-export hops the way
    `_find_generic_source` does but accepting a `def base(` without brackets.

    BUILTINS: Mojo's `enumerate` (and `iter`) are compiler builtins — a test
    file may call them with NO import line at all (test/iter/test_enumerate
    does). The stdlib's `std/iter` overloads ARE the builtin's measured
    dependent-return implementation, so a name with no import resolves there
    instead of refusing. `iter` then files no record anyway: its return
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
                if pr is not None:
                    out.append({'pr': pr,
                                'params': [p[0] for p in
                                           (getattr(s, 'params', None) or [])]})
        _FACTORY_RETURN_CACHE[key] = out
    return _FACTORY_RETURN_CACHE[key]


def _factory_return_for(fsrc, path, base, moved):
    """The `def base` overload whose pass mode matches (`moved` -> the
    `var`/owned overload, else the `ref` one), or None when there is none of
    that mode. Both overloads of a factory name the SAME wrapper; they differ
    only in the type argument (IteratorType vs IteratorOwnedType), which is
    exactly the `kind`."""
    want = 'owned' if moved else 'borrowed'
    for ov in _factory_returns(fsrc, path, base):
        if ov['pr']['kind'] == want:
            return ov
    return None


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
    """`visit(call, locals_map)` for every CallExpr, where `locals_map` is the
    innermost enclosing function's local VarDecls (None at module level). Each
    nested function starts a fresh scope from its own body, so a same-named
    local in two functions does not conflate."""
    def rec(node, locs):
        if node is None:
            return
        if isinstance(node, FunctionDef):
            l = {}
            _collect_locals(getattr(node, 'body', None), l)
            for c in _children(node):
                rec(c, l)
            return
        if isinstance(node, CallExpr):
            visit(node, locs)
        for c in _children(node):
            rec(c, locs)
    for s in stmts:
        rec(s, None)


def _seed_one_factory(gen, work, mm, base, node, locs, import_map, queue,
                      records, depth=0):
    """Evaluate ONE factory call site. Returns the record (filed in `records`
    and its wrapper enqueued as a root) or None for every refusal — in which
    case the call site is left exactly as this pass found it. The checks run
    cheapest-first, and the IS-FACTORY gate comes before the container
    resolution, so a non-factory call (`assert_equal(<list>, ...)`) never
    files a container-resolution refusal."""
    if depth > 4:
        work.refuse(f'{base}(...): nested factory depth exceeds 4')
        return None
    args = getattr(node, 'args', None) or []
    if len(args) < 1:
        return None
    home = _factory_home(gen, import_map, base)
    if not home:
        return None
    try:
        fsrc = open(home).read()
    except OSError:
        return None
    if not _factory_returns(fsrc, home, base):
        return None   # imported, but not a dependent-return factory
    # `factory_names` is an over-approximation (every imported generic); the
    # nested recursion re-validates each one, so a non-factory nested call
    # simply refuses the outer. It exists so `resolve_container` can tell a
    # nested factory call from an ordinary local.
    factory_names = set(getattr(gen, '_imported_generics', {}))
    cont = iter_factory.resolve_container(args[0], factory_names, locs)
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
    if wrapper is not None:
        wm = re.search(r'struct\s+' + re.escape(wrapper) + r'\s*\[\s*(\w+)\s*:',
                       fsrc)
        if not wm:
            work.refuse(
                f'{base}(...): wrapper {wrapper!r} has no single type parameter '
                'in its home module')
            return None
        wrapper_param = wm.group(1)
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
    if cont['kind'] == 'list':
        chome, csrc = _container_home(gen, cont['tname'])
        if not csrc:
            work.refuse(
                f'{base}(...): no module declares container {cont["tname"]!r}')
            return None
        kind = 'owned' if cont['moved'] else 'borrowed'
        rhs = iter_factory.iter_type_rhs(csrc, cont['tname'], kind)
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
    else:   # nested factory: its wrapper is the container (its own
            # `comptime IteratorType[...] = Self`), so the inner is that
            # wrapper's mangled name, registered by the recursion below.
        sub = _seed_one_factory(gen, work, mm, cont['name'], cont['node'],
                                locs, import_map, queue, records, depth + 1)
        if sub is None:
            return None
        inner_mention = sub['wrapper_mangled']
        inner_mangled = sub['wrapper_mangled']
    wrapper_mangled = None
    if wrapper is not None:
        wrapper_mangled = mm.mangle(wrapper, {wrapper_param: inner_mention})
        _register_named(gen, home, [wrapper])
    rec = {'name': base, 'wrapper': wrapper, 'wrapper_param': wrapper_param,
           'wrapper_mangled': wrapper_mangled, 'inner_mangled': inner_mangled,
           'inner_mention': inner_mention, 'kind': cont['kind'],
           'elem': cont.get('elem'),
           'elem_ctype': iter_factory._MOJO_ELEM_C.get(cont.get('elem'),
                                                       'int64_t'),
           'moved': bool(cont['moved']),
           'wrapper_kwarg': wrapper_kwarg}
    records[iter_factory.factory_call_key(base, node)] = rec
    if wrapper is None:
        # Bare `iter`: the inner (the iterator itself) is the queue root —
        # for a list container it is materialized at its element argument
        # (mangle-identical to the mention the wrappers of the same file
        # reference, so the queue's seen-set dedupes it); for a nested-
        # factory container the recursion above already enqueued the
        # container's own wrapper, which is the inner.
        if cont['kind'] == 'list':
            work.enqueue(('struct', inner_base, tuple(inner['args'])), 0, queue)
    else:
        work.enqueue(('struct', wrapper, (inner_mention,)), 0, queue)
    return rec


def _seed_factories(gen, work, stmts, queue):
    """Entry: find every factory call, evaluate it, register + enqueue its
    wrapper, and file the record the emit side reconstructs from. Lazy-imports
    `monomorphize` (which imports `gimple_codegen` at module level — the cycle
    this pass is loaded in the middle of)."""
    import monomorphize as mm
    records = gen._intu_factory_records
    import_map = _import_name_map(stmts)

    def visit(node, locs):
        base = (node.func.obj.name if isinstance(node.func, SubscriptExpr)
                and isinstance(node.func.obj, IdentExpr)
                else node.func.name if isinstance(node.func, IdentExpr)
                else None)
        if not base:
            return
        _seed_one_factory(gen, work, mm, base, node, locs, import_map, queue,
                          records)
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
    targs = elaborate.bind_type_args(tmpl, list(args))
    if targs is None:
        work.refuse(f'{base}[{", ".join(args)}]: a bracket parameter is unbound')
        return None
    try:
        mangled, concrete = mm.monomorphize_source(tmpl, targs)
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
            'src_path': src_path}


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


def _rewrite_annotations(work):
    for rec in work.records.values():
        for holder, attr in rec['sites']:
            ann = _get(holder, attr)
            if not isinstance(ann, str) or '[' not in ann:
                continue
            new = _rewrite_ann(work, ann)
            if new != ann:
                _set(holder, attr, new)


def _rewrite_ann(work, ann):
    """`ann` with every MATERIALIZED `Base[Args]` mention replaced. Bounded by
    the annotation's own bracket depth: each round that changes the string
    removes at least one bracket pair, so this cannot spin."""
    for _ in range(8):
        hit = None
        for base, args, start, end in _mentions(ann):
            mangled = work.alias.get(('struct', base, tuple(args)))
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
