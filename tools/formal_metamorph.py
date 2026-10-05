#!/usr/bin/env python3
"""METAMORPHIC testing for the formal backend: no oracle, an INVARIANT.

`tools/formal_fuzz.py` is differential: it generates a program, runs it on
CPython and on two built images, and requires the answers to be equal.  That
finds a miscompile only where the *answer happens to be observable* — the
generator has to print the value whose lowering is wrong, and the wrong value
has to differ from the right one.  Both are properties of the program, not of
the backend, and a register-allocation bug in a frame slot the program never
prints is invisible to it.

Metamorphic testing asks a different question, and asks it about the BACKEND
rather than about the program's output:

    P and T are the same program.  Whatever P answers, T must answer.

Two levers make that checkable without an oracle:

  * CPython IS still the oracle, but now for the TRANSFORMATION rather than for
    the backend.  Every transformation here is supposed to preserve meaning, so
    CPython running P and CPython running T must agree.  If they do not, the
    TRANSFORM is unsound and the tool is wrong — which is checked FIRST, on
    every single pair, before a backend is even asked.  A metamorphic harness
    whose transformation quietly changes the meaning tests nothing: every
    "divergence" would then be the tool's own, and the tally would be noise.
  * The invariant is checked against the images as well, so a divergence is
    either a metamorphic violation (the two builds of the SAME meaning disagree
    — no oracle needed, and the case a differential corpus structurally cannot
    reach) or a differential mismatch against CPython, which `formal_fuzz.py`
    would also have found.  The first is what this tool is for.

    python3 tools/formal_metamorph.py -n 60 --backends x86_64,arm64 -j 4

WHAT IS TRANSFORMED
-------------------
Ten transformations, all AST-based and all *semantics-preserving by
construction* — each one's soundness argument is in its own docstring, and each
one is a decidable syntactic predicate over the tree rather than a judgement
about what the program means:

    rename        alpha-rename a function's locals and parameters
    dead_local    add a never-read local and a dead store over it
    extra_param   add a parameter to a user function and an argument at every
                  call site
    noop_loop     add a zero-trip loop at the top of a function body
    if_true       wrap a statement in `if True:`
    swap_add      exchange the operands of an integer `+`
    extract       replace `x = e` and every use of `x` with `e` itself
    reorder       swap two adjacent independent statements
    def_order     permute a run of consecutive top-level definitions
    inline_helper substitute a single-`return` function into its call sites

The first seven are REGISTER/LAYOUT perturbations: they change nothing about the
computation and everything about the names, the live ranges, the slot count, the
frame size and the control-flow graph the emitter walks.  `reorder` and
`def_order` change ORDER, and `inline_helper`/`extract` change SHAPE.  A bug in
slot assignment, spill placement, frame layout, stack alignment or emission
order is invisible to a differential corpus whose programs all have the same
shape, and metamorphic pairs are the cheapest way to reach it: the two programs
have KNOWN-EQUAL answers, so any difference is a bug with no oracle in the way.

WHY CPYTHON'S OWN PARSER
------------------------
The transformations are applied to CPython's `ast`, not to `fire_compiler`'s.
That is a deliberate choice with two costs and three advantages, and it is worth
stating because a reader will wonder:

  * COST: comments and blank lines do not survive, so a finding's twin does not
    read like the program it came from, and the 8 examples of
    `formal/examples` that spell Mojo-only syntax (`var`, `fn`) cannot be
    transformed at all — they are reported as `skipped_examples`, never
    silently dropped.
  * ADVANTAGE: the tree being rewritten is the one CPython will execute, so the
    oracle's reading of `T` is derived from the SAME parse rather than from a
    second implementation's, and the two cannot disagree about what `T` says. A
    metamorphic tool whose transformation and whose oracle parse the file
    differently is measuring the parser as much as the backend.
  * ADVANTAGE: the corpus is the intersection of the two languages already —
    `formal_fuzz.py` emits no `var`, no `struct`, no comprehension and no
    f-string precisely so that one text runs on three engines — so nothing in
    the measured corpus is lost by this choice.

WHAT IS MEASURED
----------------
  match                 every engine that answered P also answered T, the same.
  METAMORPH-<ARCH>      the image answers P and T DIFFERENTLY.  THE FINDING.
                        Needs no oracle: `T` is `P`, so two builds of one
                        meaning disagree.
  MISMATCH-<ARCH>       the image disagrees with CPython about P or about T.
                        Also a finding — a silent miscompile — and the twin is
                        usually what localises it: which transform turned a
                        wrong answer into a right one, or the other way round,
                        is the shape of the backend's bug.
  TWIN-DIVERGES-<ARCH>  one machine lowers P and refuses T, or vice versa.  A
                        backend bug and not a documented limit: the twin BUILT,
                        so the construct is representable and the machine that
                        declined it is wrong about the program.
  REFUSAL-DIVERGES-*    the two machines disagree about a refusal, or one
                        machine's words change under a transform that does not
                        change the program.  The same rule
                        `formal_fuzz.py::classify` applies, on the pair: the two
                        architectures are ONE language implementation, so two
                        refusals in different words are a finding.
  transform-invalid     CPython answered P and T differently.  A BUG IN THIS
                        TOOL, reported at the same loudness as a backend bug
                        because it invalidates every other row: see above.
  transform-crash       a transformation raised.  Also a tool bug, and also
                        loud: a transform that silently declines what it should
                        have applied to is how a corpus stops measuring.
  not-answerable        CPython could not finish the program, so the pair says
                        nothing and nothing is claimed.
  skip:<transform>      the transformation does not apply to this program.  Not
                        a finding — most programs have no `+` to swap — but it
                        is COUNTED, per transform, because "the transform
                        applied to nothing" is indistinguishable on a screen
                        from "the transform never ran".

WHAT THIS IS NOT
----------------
It is not a replacement for `formal_fuzz.py`, and it does not subsume it: a
metamorphic pair needs the ORIGINAL program to be interesting in its own right
(the corpus is reused for exactly that reason, and `formal/examples` is read
verbatim), and a transformation can only reach a construct a program already
contains.  The two tools share their harness — the build, the runner and the
CPython oracle are `formal_fuzz`'s, imported and never re-spelled, for the
reason `formal_proof_fuzz.py` gives.

It is also not a proof of anything.  A sweep over N programs says "the backend
was right about N × T pairs"; `bugs/FORMAL_metamorphic_ledger.md` says which
pairs those were, so the next session can see what stopped being covered.
"""

import argparse
import ast
import collections
import copy
import json
import os
import random
import re
import shutil
import subprocess  # noqa: F401  — re-exported for callers that shim this module
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.path.insert(0, HERE)

import formal_fuzz as F  # noqa: E402  — the build, the runner, the CPython oracle


# ── scope resolution ────────────────────────────────────────────────────────
#
# Alpha-renaming needs to know, for EVERY name in the tree, the scope it is
# BOUND IN — not whether the spelling appears somewhere, but whether two
# occurrences are the same binding.  `def f(x): return x` next to a nested
# `def g(x)` has three `x`s and two different bindings, and renaming all three
# is a NameError at run time.
#
# So the real scope tree is built with CPython's own rules — module, function,
# lambda, class, comprehension — rather than counting spellings.  The rules
# implemented here, and why each one earns its place:
#
#   * a FUNCTION binds its parameters and every name assigned anywhere in its
#     body (not only before the use — Python's UnboundLocalError is exactly
#     why an assignment later in the body still makes the name local), MINUS any
#     name declared `global`/`nonlocal`;
#   * a `global`/`nonlocal` declaration moves a name OUT of the function that
#     spells it and into the scope it names;
#   * a CLASS body binds its own names, and a nested function's reads are
#     resolved without it: `_innermost` only ever returns a class scope for an
#     occurrence DIRECTLY in the class body, which is the one place a class
#     binding is in scope.  That is a simplification (a real class body's
#     enclosing-function names are reachable in CPython through the class
#     statement's own evaluation, and are handled by `_bind_outer_values`);
#   * a COMPREHENSION is its own scope since Python 3, so `[x for x in xs]`
#     does not leak `x` into the enclosing function, and it may READ the
#     enclosing scopes — which is how a closure's capture is represented here,
#     and therefore how `rename` rewrites both halves of a capture consistently.

class Scope:
    """One binding scope, its parent, and the names it binds."""

    __slots__ = ("kind", "node", "parent", "bindings", "children")

    def __init__(self, kind, node, parent):
        self.kind = kind
        self.node = node
        self.parent = parent
        self.bindings = set()
        self.children = []

    def __repr__(self):
        return f"<Scope {self.kind} {getattr(self.node, 'name', '')!r}>"


def _bind_target(node, out):
    """Every name a target expression binds.  Walks tuples, lists and stars."""
    if isinstance(node, ast.Name):
        out.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            _bind_target(elt, out)
    elif isinstance(node, ast.Starred):
        _bind_target(node.value, out)


def _fn_outer_values(fn):
    """Names a nested `def` evaluates in the ENCLOSING scope, not its own.

    A `def`'s decorators, its defaults and its class bases are evaluated where
    the `def` is written, so a name read there is a read of the enclosing
    scope's binding.  `rename` uses this to refuse to rename a local that a
    nested definition's default expression reads — the alternative is that the
    default's occurrence resolves (under the scope tree below) to the nested
    function rather than to the function that owns the name, and the rename
    would move the default but not the binding it is written against.
    """
    out = set()
    args = fn.args
    for d in list(args.defaults) + [x for x in args.kw_defaults if x]:
        out |= _names_in(d)
    for d in getattr(fn, "decorator_list", []):
        out |= _names_in(d)
    for b in getattr(fn, "bases", []):
        out |= _names_in(b)
    for kw in getattr(fn, "keywords", []):
        out |= _names_in(kw.value)
    return out


#: The node types whose payload is SOURCE TEXT rather than a subtree CPython's
#: printer walks.  `ast.unparse` writes a `FormattedValue`'s expression from the
#: `Name` node, but it writes a PEP 750 `TemplateStr`'s `Interpolation` the way
#: it found it — and `t"v={s2}"` is a `TemplateStr` on Python 3.14, so a reader
#: that only knows `JoinedStr` finds `s2` in neither and renames it anyway.
#: Resolved by attribute rather than by name so this file still imports on a
#: Python without PEP 750.
_INTERPOLATED_NODES = tuple(
    getattr(ast, n) for n in ("JoinedStr", "FormattedValue", "TemplateStr",
                              "Interpolation") if hasattr(ast, n))


def _interpolated_names(module):
    """Names read inside an f-string / t-string, which are SOURCE TEXT.

    `f"v={s2}"` holds the expression as text in `FormattedValue.value`, and
    `ast.unparse` writes it back out without consulting the `Name` node — so a
    rename that rewrote the `Name` would move one copy of the name and leave
    the other, and the twin would raise `NameError` on the copy that survived.
    Rewriting the text as well would mean re-printing an expression into a
    string literal, and a mis-spelled one is a `SyntaxError` rather than a
    wrong answer, so the choice is to leave the name alone.
    """
    out = set()
    for n in ast.walk(module):
        if isinstance(n, _INTERPOLATED_NODES):
            out |= _names_in(n)
    return out


def _names_in(node):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
    return out


class _ScopeBuilder(ast.NodeVisitor):
    """Builds the scope tree, then resolves each occurrence to its binding."""

    def __init__(self, module):
        self.module_scope = Scope("module", module, None)
        self.scopes = {id(module): self.module_scope}
        self.node_scope = {}          # node id -> innermost enclosing Scope
        self.redirect = {}            # (scope id, name) -> declared target
        self.cur = self.module_scope

    # -- the tree ----------------------------------------------------------
    def _child(self, kind, node, parent):
        s = Scope(kind, node, parent)
        parent.children.append(s)
        self.scopes[id(node)] = s
        return s

    def _bind_in(self, scope, name):
        scope.bindings.add(name)

    def visit_Module(self, node):
        self._bind_body(self.module_scope, node.body)

    def _visit_function(self, node):
        s = self._child("function", node, self.cur)
        args = node.args
        # Decorators, defaults and annotations are EVALUATED where the `def` is
        # written, so they are visited with the OUTER scope current.  (A local
        # annotation inside a body is NOT evaluated at all — PEP 526 — so it is
        # deliberately not visited anywhere.)
        for d in node.decorator_list:
            self.visit(d)
        for d in list(args.defaults) + [x for x in args.kw_defaults if x]:
            self.visit(d)
        if node.returns is not None:
            self.visit(node.returns)
        params = (list(args.posonlyargs) + list(args.args)
                  + list(args.kwonlyargs))
        if args.vararg:
            params.append(args.vararg)
        if args.kwarg:
            params.append(args.kwarg)
        for a in params:
            self._bind_in(s, a.arg)
            if a.annotation is not None:
                self.visit(a.annotation)
        outer, self.cur = self.cur, s
        try:
            self._note_declarations(s, node)
            self._bind_body(s, node.body)
            self.generic_visit(node)
        finally:
            self.cur = outer

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Lambda(self, node):
        s = self._child("lambda", node, self.cur)
        args = node.args
        for a in (list(args.posonlyargs) + list(args.args)
                  + list(args.kwonlyargs)):
            self._bind_in(s, a.arg)
        if args.vararg:
            self._bind_in(s, args.vararg.arg)
        if args.kwarg:
            self._bind_in(s, args.kwarg.arg)
        outer, self.cur = self.cur, s
        try:
            self.generic_visit(node)
        finally:
            self.cur = outer

    def visit_ClassDef(self, node):
        s = self._child("class", node, self.cur)
        for d in node.decorator_list:
            self.visit(d)
        for b in node.bases:
            self.visit(b)
        for kw in node.keywords:
            self.visit(kw.value)
        outer, self.cur = self.cur, s
        try:
            self._bind_body(s, node.body)
            self.generic_visit(node)
        finally:
            self.cur = outer

    def _comprehension_scope(self, node):
        s = self._child("comprehension", node, self.cur)
        outer, self.cur = self.cur, s
        try:
            for gen in node.generators:
                self.visit(gen.iter)
                targets = set()
                _bind_target(gen.target, targets)
                for t in targets:
                    self._bind_in(s, t)
                for cond in gen.ifs:
                    self.visit(cond)
            # `key`/`value`, not `elt`: a `DictComp` has no `elt` and no
            # `keywords`, and reading either anyway raised `AttributeError` on
            # every `{k: v for …}` in the corpus — which is the `containers`
            # mix, so a whole mix was unmeasurable rather than measured empty.
            for field in ("elt", "key", "value"):
                if hasattr(node, field):
                    self.visit(getattr(node, field))
            for kw in getattr(node, "keywords", None) or []:
                self.visit(kw.value)
        finally:
            self.cur = outer

    visit_ListComp = _comprehension_scope
    visit_SetComp = _comprehension_scope
    visit_GeneratorExp = _comprehension_scope
    visit_DictComp = _comprehension_scope

    def _note_declarations(self, scope, fn):
        """Record `global`/`nonlocal` names, which are not this scope's own.

        The names are also dropped from the scope's bindings — but by
        `_bind_body`, once it has seen the WHOLE body, because the declaration
        and the assignment it contradicts can be in either order: `global G7`
        on the first line and `G7 = 42` inside an `if` eight lines down is one
        binding, and a discard-then-rebind in source order leaves the name in the
        scope.  Measured on `mmsound:1` of the `globals` mix: `G7` came out of
        `main` as a LOCAL, so `rename` rewrote it to `_mmr0` and the twin died
        of `NameError`.  CPython caught it; that is the oracle doing its job.
        """
        for stmt in fn.body:
            for n in ast.walk(stmt):
                if isinstance(n, (ast.Global, ast.Nonlocal)):
                    for name in n.names:
                        self.redirect[(id(scope), name)] = name

    def _bind_body(self, scope, body):
        """Bind every name assigned anywhere in `body`, then visit it.

        The binding pass is a walk that REFUSES to descend into a nested
        `def`/`lambda`/`class` body: "assigned anywhere in this function" is not
        "assigned on the path that reaches this use", and descending would steal
        the nested function's own locals.  Visiting is a second pass, because
        the visitor is what creates the nested scopes and the two orders fight
        if they are interleaved.
        """
        declared = set()
        for stmt in body:
            for n in _walk_skipping_scopes(stmt):
                if isinstance(n, (ast.Global, ast.Nonlocal)):
                    declared |= set(n.names)
        for stmt in body:
            for n in _walk_skipping_scopes(stmt):
                if isinstance(n, ast.Name) and isinstance(n.ctx,
                                                         (ast.Store, ast.Del)):
                    if n.id not in declared:
                        self._bind_in(scope, n.id)
        for name in declared:
            scope.bindings.discard(name)
        for stmt in body:
            self.visit(stmt)

    # -- resolution --------------------------------------------------------
    def finish(self):
        """Fill `node_scope`, innermost scope wins.

        Scopes are visited in pre-order (a parent before its children) and each
        one's whole subtree is walked, so a deeper scope's assignment to
        `node_scope` overwrites the shallower one it inherits from an ancestor.
        One walk per scope instead of a containment test per occurrence, which
        is what keeps this a tool that can afford to rebuild the tree once per
        transformation.
        """
        for scope in _preorder(self.module_scope):
            for n in ast.walk(scope.node):
                self.node_scope[id(n)] = scope
        return self

    def scope_of(self, node):
        return self.node_scope.get(id(node), self.module_scope)

    def bind_of(self, node):
        """The `Scope` an occurrence resolves to, by CPython's lookup rules."""
        name = getattr(node, "id", None)
        if name is None:
            name = getattr(node, "arg", None)
        s = self.scope_of(node)
        while s is not None:
            if s.kind == "function" and (id(s), name) in self.redirect:
                target = self.redirect[(id(s), name)]
                up = s.parent
                while up is not None and target not in up.bindings:
                    up = up.parent
                if up is not None:
                    return up
            if name is not None and name in s.bindings:
                return s
            s = s.parent
        return self.module_scope

    def run(self, module):
        self.visit(module)
        return self.finish()


def _preorder(scope):
    out = [scope]
    for child in scope.children:
        out.extend(_preorder(child))
    return out


#: The node types that open a BINDING SCOPE of their own since Python 3.  A
#: comprehension's target is invisible to the function that holds it, and
#: binding it there made `v` a local of `def f(t): return [v for v in xs]` —
#: so `rename` renamed the enclosing `v` and the comprehension's `v` was left
#: behind.  Found by the hand-written corpus in `test_formal_metamorph.py`.
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                  ast.ClassDef, ast.ListComp, ast.SetComp, ast.DictComp,
                  ast.GeneratorExp)


def _walk_skipping_scopes(root):
    """`ast.walk` that does not descend into a nested binding scope.

    With ONE exception, and the exception is PEP 572: a walrus inside a
    comprehension binds in the ENCLOSING scope (`[y := f(x) for x in xs]` leaves
    `y` bound in the function), so the comprehension's `NamedExpr` targets are
    collected even though the rest of its subtree is not walked.  A reader that
    skipped the whole subtree would call `y` free, and `rename` would then
    rewrite a use of it while the walrus kept its spelling — the same
    `NameError` class as every other half-renamed pair in this file.
    """
    out = []
    stack = [root]
    while stack:
        node = stack.pop()
        out.append(node)
        if node is not root and isinstance(node, _NESTED_SCOPES):
            for n in ast.walk(node):
                if isinstance(n, ast.NamedExpr) \
                        and isinstance(n.target, ast.Name):
                    out.append(n.target)
            continue
        stack.extend(ast.iter_child_nodes(node))
    return out


# ── the per-program analysis ────────────────────────────────────────────────

_INT_OPS = (ast.Add, ast.Sub, ast.Mult, ast.LShift, ast.RShift, ast.BitAnd,
            ast.BitOr, ast.BitXor, ast.Mod, ast.FloorDiv)


def _is_int_literal(node):
    """An integer literal, optionally negated.  `True` is NOT an int here."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) \
            and not isinstance(node.value, bool):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub,
                                                              ast.UAdd)):
        return _is_int_literal(node.operand)
    return False


class Analysis:
    """Everything the transformations need to know about one program.

    Rebuilt per TRANSFORMATION rather than shared, so a transform that mutates
    the tree in place (`reorder`, `swap_add`) cannot leak its edit into the next
    one: the two would be measured on a program neither of them was given.
    """

    def __init__(self, module):
        self.module = module
        self.builder = _ScopeBuilder(module).run(module)
        self.scopes = self.builder.scopes
        self.functions = [n for n in ast.walk(module)
                          if isinstance(n, (ast.FunctionDef,
                                            ast.AsyncFunctionDef))]
        self.parents = _parent_index(module)
        self.arg_keywords = {n.arg for n in ast.walk(module)
                             if isinstance(n, ast.keyword) and n.arg}
        self.store_counts = collections.Counter(
            n.id for n in ast.walk(module)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
        self.all_names = _all_names(module)
        self.module_bindings = set(self.scopes[id(module)].bindings)
        self._int_params: set = set()
        self.int_only = self._int_only()

    # -- lookups -----------------------------------------------------------
    def parent_of(self, node):
        return self.parents.get(id(node))

    def locals_of(self, fn):
        return set(self.scopes[id(fn)].bindings)

    def copy_of(self, fn):
        """`fn`'s counterpart in the deep copy `an` was built from.

        `ast.walk` order is a function of the tree's SHAPE, and a deep copy has
        the same shape, so the Nth function of the copy is the Nth of the
        original.  It is spelled as a helper because three transforms need it
        and "index into `ast.walk` again" is the kind of line that is right
        until the tree grows a field.
        """
        return self.functions[self.functions.index(fn)]

    def fresh(self, stem, taken=()):
        """A name no one in this program uses, so a rename cannot capture."""
        used = self.all_names | set(taken)
        i = 0
        while True:
            cand = f"_mm{stem}{i}"
            if cand not in used:
                return cand
            i += 1

    def _int_only(self):
        """Names whose value is an INTEGER at every binding site.

        The predicate `swap_add` needs, and the reason it cannot be "any
        operand": `a + b` is commutative for integers and is NOT for lists,
        tuples or dicts (`[1] + [2]` and `[2] + [1]` are different values), so
        a transform that swapped operands it had not classified would
        manufacture a disagreement out of its own imprecision.

        The classification is a LEAST FIXPOINT over "this name holds an int",
        because the honest answer for a name is the conjunction over its stores
        and a greatest fixpoint would license a name one int store out of three
        had made int-valued — which is precisely the case the oracle would then
        report as `transform-invalid`, on a corpus whose whole point is that the
        transforms are sound. Starting from the empty set and only adding names
        every store of which is an int expression cannot do that.

        A name with NO store is a parameter, and a parameter's value is not
        knowable here, so a parameter is not in the set: `swap_add` will not
        touch `f(p)` on the strength of `p` being a parameter.
        """
        stores = collections.defaultdict(list)
        for n in ast.walk(self.module):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                stores[n.id].append(n)
        scopes_of = collections.defaultdict(set)
        for n in ast.walk(self.module):
            if isinstance(n, ast.Name):
                scopes_of[n.id].add(id(self.builder.bind_of(n)))
        known = self._int_names(stores)
        out = set()
        for name, nodes in stores.items():
            if len(scopes_of[name]) != 1:
                continue
            if name in known:
                out.add(name)
        return out | (known & self._int_params)

    def _int_names(self, stores):
        """`{name: the name holds an int}` as a least fixpoint.

        Seeded from the PARAMETERS as well as from nothing, because a parameter's
        value is not knowable from its own stores — it has none — and a corpus
        that passes integers everywhere makes `swap_add` unreachable without
        this.  The seeding is sound because it comes from the CALL SITES
        (`_param_int_names`) and the fixpoint only ever adds names it can
        prove, so the answer is a superset of the store-only one and every name
        in it is still provably int-valued.

        The rounds alternate between the two questions — "which parameters get
        only integer arguments" and "which names are integer-valued" — because
        each can feed the other: `def f(n): return n + 1` called as `f(k)` where
        `k = 3` needs `k` known before `n` is, and `def g(k): return f(k) + 1`
        needs `n` known before the second `k` is.  Four rounds is enough because
        the corpus's call depth is far below that, and the loop stops as soon as
        a round adds nothing.
        """
        known: set = set()
        for _round in range(5):
            params = self._param_int_names(stores, known)
            if params == self._int_params and known:
                break
            self._int_params = params
            grown = set(params)
            changed = True
            rounds = 0
            while changed and rounds <= len(stores) + 2:
                changed = False
                rounds += 1
                for name in sorted(stores):
                    if name in grown:
                        continue
                    if all(self._store_is_int(n, grown) for n in stores[name]):
                        grown.add(name)
                        changed = True
            if grown == known:
                break
            known = grown
        return known

    def _param_int_names(self, stores, known):
        """Parameters whose every call site passes an integer argument.

        Decidable, and the reason is that the corpus calls its helpers with
        literals: `f13(0, (1 if 1 else 7), f13(-24, 25, 15))` says `p14` is an
        int at every call, so `p14` is an int inside `f13`.  The exclusions are
        the ones that make it an argument rather than a guess:

          * `main`, whose call is emitted by the build's startup stub and is not
            in the text at all;
          * a function used as a VALUE (passed, bound, used as an attribute or a
            keyword name), because then some call is not in the text;
          * a function with a DEFAULT parameter, which a call may omit;
          * a call with `*args`/`**kwargs`, whose arity is not knowable;
          * a call with the wrong arity for the signature.
        """
        out: set = set()
        for fn in self.functions:
            if fn.name == "main" or _used_as_value(self.module, fn.name):
                continue
            args = fn.args
            if args.vararg or args.kwarg or args.kwonlyargs:
                continue
            if any(d is not None for d in args.defaults):
                continue
            params = [a.arg for a in _params(fn)]
            sites = [n for n in ast.walk(self.module)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == fn.name]
            if not sites:
                continue
            ok = True
            for call in sites:
                if any(k.arg is None for k in call.keywords):
                    ok = False
                    break
                if len(call.args) > len(params):
                    ok = False
                    break
                bound = dict(zip(params, call.args))
                for kw in call.keywords:
                    if kw.arg in bound:
                        ok = False            # given twice
                        break
                    bound[kw.arg] = kw.value
                if not ok:
                    break
                if set(bound) != set(params):
                    ok = False
                    break
                if not all(self._int_expr(v, known)
                           for v in bound.values()):
                    ok = False
                    break
            if ok:
                out |= set(params)
        return out

    def _store_is_int(self, node, known):
        """Whether the store at `node` gives the name an integer value."""
        parent = self.parent_of(node)
        if isinstance(parent, ast.Assign):
            return self._int_expr(parent.value, known)
        if isinstance(parent, ast.AnnAssign):
            return self._int_expr(parent.value, known)
        if isinstance(parent, ast.AugAssign):
            return (isinstance(parent.op, _INT_OPS)
                    and self._int_expr(parent.value, known))
        return False

    def _int_expr(self, node, known):
        """Whether `node` provably evaluates to an integer.

        Deliberately conservative about every shape whose result type depends on
        something this cannot see: a call, a subscript, an attribute read and
        every container literal are False, because the corpus's `containers` and
        `strmeth` mixes bind names to those and a subscript of a list of words
        is an int here and a list of bytes is not.
        """
        if node is None:
            return False
        if _is_int_literal(node):
            return True
        if isinstance(node, ast.Name):
            return node.id in known
        if isinstance(node, ast.BinOp):
            return (isinstance(node.op, _INT_OPS)
                    and self._int_expr(node.left, known)
                    and self._int_expr(node.right, known))
        if isinstance(node, ast.UnaryOp):
            return (isinstance(node.op, (ast.USub, ast.UAdd, ast.Invert,
                                         ast.Not))
                    and self._int_expr(node.operand, known))
        if isinstance(node, ast.BoolOp):
            return all(self._int_expr(v, known) for v in node.values)
        if isinstance(node, ast.Compare):
            # A comparison is 0 or 1 on both engines, and both are integers.
            return True
        if isinstance(node, ast.IfExp):
            # The result is one of the two arms, so the arms decide it — the
            # TEST need not be classified, which is why this is not a
            # conjunction over all three.
            return (self._int_expr(node.body, known)
                    and self._int_expr(node.orelse, known))
        return False

    # -- stores ------------------------------------------------------------
    def stores_of(self, name):
        """Every store of `name` in the whole program, as `ast.Name` nodes."""
        return [n for n in ast.walk(self.module)
                if isinstance(n, ast.Name) and n.id == name
                and isinstance(n.ctx, ast.Store)]

    def in_nested_scope(self, fn, node):
        """Whether `node` sits inside a scope nested in `fn`."""
        cur = node
        while True:
            parent = self.parent_of(cur)
            if parent is None or parent is fn:
                return False
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.Lambda, ast.ClassDef)):
                return True
            cur = parent

    def statement_index(self, fn, node):
        """`node`'s index in `fn`'s top-level body, or None if it has none."""
        cur = node
        while True:
            parent = self.parent_of(cur)
            if parent is None or parent is fn:
                break
            cur = parent
        for i, stmt in enumerate(fn.body):
            if stmt is cur:
                return i
        return None
        return False


def _parent_index(root):
    out = {}
    for parent in ast.walk(root):
        for child in ast.iter_child_nodes(parent):
            out[id(child)] = parent
    return out


def _all_names(module):
    out = set()
    for n in ast.walk(module):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.keyword) and n.arg:
            out.add(n.arg)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _replace_child(parent, old, new):
    """Put `new` where `old` sits in `parent`.  False if it is not there."""
    for field, value in ast.iter_fields(parent):
        if value is old:
            setattr(parent, field, new)
            return True
        if isinstance(value, list):
            for i, item in enumerate(value):
                if item is old:
                    value[i] = new
                    return True
    return False


# ── the transformations ─────────────────────────────────────────────────────
#
# Each is `apply(module, an, rng)` returning the (possibly mutated) module, or
# raising `NotApplicable`.  `NotApplicable` is not a failure: "this program has
# no `+` whose operands are integers" is the ordinary answer, and the driver
# counts it per transform so a transform that stopped applying is visible
# rather than silent.
#
# EVERY one of them is checked by CPython before a backend is asked
# (`transform-invalid`), because an unsound transform invalidates the whole row
# it appears in.  The oracle is not a formality here; it is what makes "the two
# builds disagree" mean "the backend is wrong".

#: The names a receiver parameter is spelled with, read from the ONE table the
#: backend keeps them in (`formal/model.py::RECEIVER_PARAMETER_SPELLINGS`, which
#: `struct_receivers` and `method_declares_receiver` share — so the two cannot
#: come apart).  A second copy here would be a second opinion about which
#: spellings count as a receiver.
_RECEIVER_SPELLINGS = set(F.M.RECEIVER_PARAMETER_SPELLINGS)


class NotApplicable(Exception):
    """This transformation does not apply to this program."""


def _require(cond, why):
    if not cond:
        raise NotApplicable(why)


def _is_constructor(an, fn):
    """Whether `fn` is a class's `__init__`.

    And why that is a question a transformation has to ask before it adds a
    statement to a function body.

    On this path `C(...)` with a user-defined constructor is NOT lowered as a
    call: `formal/build.py` INLINES the constructor's body at the construction
    site, storing each of its `self.<field> = …` assignments into the fresh
    block there.  So the constructor's body is not a function body — it is the
    representation of the construction, and its SHAPE is the construct.  A
    constructor whose body contains an `if`, a loop, or a plain local store is
    declined with a message naming exactly that:

        constructing C with arguments is a call to a user-defined `__init__`
        whose body this path does not inline: a `if` statement

    Measured on both architectures, for `if_true`, `noop_loop` and `dead_local`
    alike, so it is the SHAPE and not the transformation.

    That refusal is CORRECT — the message says which construct and gives the
    program that does have a representation — and it is not a backend finding.
    It is a boundary the TRANSFORMATION must not cross, because a transform that
    changes a construct's shape has not produced the same program on this
    target, and a metamorphic pair built on that premise measures nothing.
    """
    if fn.name != "__init__":
        return False
    parent = an.parent_of(fn)
    return isinstance(parent, ast.ClassDef)


def _self_field_stores(node):
    """Whether `node` is `self.<field> = <expr>` and nothing else."""
    return (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Attribute)
            and isinstance(node.targets[0].value, ast.Name)
            and node.targets[0].value.id == "self")


def _pick_function(an, rng):
    """One function to perturb, chosen deterministically from the seed."""
    _require(an.functions, "no function in the program")
    return rng.choice(an.functions)


def _params(fn):
    a = fn.args
    return (list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
            + ([a.vararg] if a.vararg else [])
            + ([a.kwarg] if a.kwarg else []))


# -- 1. rename ---------------------------------------------------------------

def t_rename(module, an, rng):
    """Alpha-rename every local and parameter of ONE function.

    SOUNDNESS.  The mapping is built per FUNCTION SCOPE from the scope tree, and
    an occurrence is rewritten only when `bind_of` says its binding is that
    scope — so a nested `def g(x)` shadowing an outer `x` has its own
    occurrences untouched, while a closure that CAPTURES an outer local has both
    halves rewritten and stays captured.  That is the whole reason this is not a
    textual substitution, and it is what makes the transform interesting: it
    changes every name the emitter and the register allocator see while the
    meaning is bit-identical.

    Four exclusions, each for a concrete reason, and each of them a way the
    transform could otherwise produce a `NameError` rather than a rename:

      * a parameter spelled as a KEYWORD ARGUMENT at any call site
        (`keyword.arg` is a string, not a `Name`, so no scope walker sees it):
        renaming the parameter would make every `f(x=1)` call a TypeError;
      * a local read by a nested definition's DEFAULT or DECORATOR expression,
        which is evaluated in the enclosing scope and which the scope tree
        above resolves to the nested function (`_fn_outer_values`);
      * a local read inside an f-string or t-string, whose expression is SOURCE
        TEXT that `ast.unparse` writes back without consulting the `Name` node
        (`_interpolated_names`) — renaming one half of that pair produces a
        `NameError` in the twin; measured on 10 programs of the `fstrings`
        mix;
      * the name `main`, which the formal runtime's entry stub looks up BY NAME
        (`formal/build.py`), so renaming it yields an image with no entry point
        rather than a renamed one;
      * a RECEIVER parameter's spelling — `formal/model.py`'s own
        `RECEIVER_PARAMETER_SPELLINGS`, imported rather than re-spelled, because
        a method's receiver is identified by the NAME its first parameter is
        written with and a rename therefore deletes it.  Measured on the
        `classes` mix: 20 of 30 twins came out `TWIN-DIVERGES` with
        `C5.m15() is declared with parameters and no receiver: its first
        parameter is an ordinary argument`.  The receiver is not a parameter
        this path can rename, so it is the same class as `main`: a name the
        target looks up rather than one it computes with;
      * nothing at all: a function whose every local is excluded is skipped and
        the next one is tried, rather than the transform claiming a rename it
        did not make.
    """
    order = list(an.functions)
    rng.shuffle(order)
    for fn in order:
        scope = an.scopes[id(fn)]
        if scope.kind != "function":
            continue
        blocked = (set(an.arg_keywords) | {"main"} | _interpolated_names(module)
                   | _RECEIVER_SPELLINGS)
        for inner in an.functions:
            if inner is fn:
                continue
            blocked |= _fn_outer_values(inner)
        names = sorted(n for n in an.locals_of(fn) if n not in blocked)
        if not names:
            continue
        mapping = {}
        for n in names:
            mapping[n] = an.fresh("r", tuple(mapping.values()))
        scope_id = id(scope)
        renamed = 0
        for occ in ast.walk(module):
            # `ast.arg` as well as `ast.Name`: a parameter is renamed in BOTH
            # halves, and a transform that renames only the occurrences produces
            # `def f(_mmr0): return _mmr0 - 1` under a parameter still spelled
            # `n21` — a NameError in the twin, which the oracle reports as
            # `not-answerable` rather than as the tool defect it is.  Measured
            # on 6 of 30 programs of `metamorph`/`calls` before this was fixed.
            if not isinstance(occ, (ast.Name, ast.arg)):
                continue
            spelling = occ.id if isinstance(occ, ast.Name) else occ.arg
            if spelling in mapping and id(an.builder.bind_of(occ)) == scope_id:
                if isinstance(occ, ast.Name):
                    occ.id = mapping[spelling]
                else:
                    occ.arg = mapping[spelling]
                renamed += 1
        if renamed:
            return module
    raise NotApplicable("every local is excluded")


# -- 2. dead local -----------------------------------------------------------

def t_dead_local(module, an, rng):
    """Add a never-read local and then a DEAD STORE over it.

    SOUNDNESS.  The name is fresh in this program — checked against every
    identifier in it — so nothing that was read can start reading it, and the
    statements go at the TOP of a function body, so they cannot straddle a use
    of a name they share (they share none).  The first store is dead because
    nothing between it and the second reads the name; the second is dead
    because the function never reads the name afterwards.  `AugAssign` is
    deliberately not used: `x = x + 1` on an uninitialised name is a NameError,
    and a transform that has to reason about that is a transform that will
    eventually get it wrong.

    The point is not the values (0 and 1) but the EFFECT on the backend: one
    more local to allocate, one more slot, and one more store to a slot nothing
    reads — which is exactly the case where a frame-slot map that is off by one
    stays off by one silently.
    """
    fn = _pick_function(an, rng)
    if _is_constructor(an, fn):
        raise NotApplicable("a constructor's body IS the construction this "
                            "path inlines, so adding a statement changes the "
                            "construct (see `_is_constructor`)")
    dead = an.fresh("d")
    stmts = ast.parse(f"{dead} = 0\n{dead} = 1\n").body
    ast.copy_location(stmts[0], fn)
    ast.copy_location(stmts[1], fn)
    fn.body[0:0] = stmts
    ast.fix_missing_locations(module)
    return module


# -- 3. extra parameter ------------------------------------------------------

def t_extra_param(module, an, rng):
    """Add a parameter to a user function and an argument at every call site.

    SOUNDNESS.  The signature must have no `*args` and no `**kwargs` (an extra
    positional parameter would be swallowed by a `*args`, and a keyword-only
    section is a signature this transform does not model), `main` is excluded
    because the formal runtime finds the entry point by name and its call is
    emitted by the build's startup stub rather than by the source — so there is
    no call site in the text to rewrite — and every call site is found by AST,
    so a call cannot be missed.  The appended argument is the literal `0` and
    the BODY is not touched, so the new parameter is read by nothing.

    The argument is passed as a KEYWORD (`f(a, b, _mmp0=0)`) rather than
    positionally: a keyword cannot be mistaken for a positional by a call that
    already has one, and it does not need the parameter to be last.
    """
    cands = [f for f in an.functions
             if f.name != "main" and not f.args.vararg and not f.args.kwarg
             and not f.args.kwonlyargs
             and not any(d is not None for d in f.args.defaults)]
    if not cands:
        raise NotApplicable("no function with a signature this transform "
                            "models")
    order = list(cands)
    rng.shuffle(order)
    for fn in order:
        sites = [n for n in ast.walk(module)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == fn.name]
        if not sites:
            continue
        if any(any(k.arg is None for k in c.keywords) for c in sites):
            continue           # a call with *args/**kwargs: refuse this one
        name = an.fresh("p")
        for call in sites:
            call.keywords.append(ast.keyword(arg=name,
                                             value=ast.Constant(0)))
        fn.args.args.append(ast.arg(arg=name))
        ast.fix_missing_locations(module)
        return module
    raise NotApplicable("no function with a call site this transform models")


# -- 4. no-op loop -----------------------------------------------------------

def t_noop_loop(module, an, rng):
    """Add a zero-trip loop at the top of a function body.

    SOUNDNESS.  `range(0, 0)` is empty in CPython and in `formal/model.py` — the
    same `for … in range` the corpus's own `for` family emits — so the body
    never executes and nothing it could do happens.  The body is a real
    statement rather than `pass` on purpose: `pass` gives the emitter an EMPTY
    block, which is a construct this path may decline, and a transform whose
    twin is refused measures the refusal instead of the loop.

    `main` is allowed here and every other place it is not: adding a statement
    before `main`'s body cannot change what the runtime looks up.
    """
    fn = _pick_function(an, rng)
    if _is_constructor(an, fn):
        raise NotApplicable("a constructor's body IS the construction this "
                            "path inlines, so adding a loop changes the "
                            "construct (see `_is_constructor`)")
    idx = an.fresh("l")
    loop = ast.parse(f"for {idx} in range(0, 0):\n    {idx} = {idx} + 1\n").body[0]
    ast.copy_location(loop, fn)
    fn.body.insert(0, loop)
    ast.fix_missing_locations(module)
    return module


# -- 5. `if True:` -----------------------------------------------------------

def t_if_true(module, an, rng):
    """Wrap ONE statement of a function body in `if True:`.

    SOUNDNESS.  `if True` is taken unconditionally, so the guarded statement runs
    exactly when it did.  Three restrictions keep the guard from becoming a
    different construct rather than the same one:

      * the statement must not be a `def`/`class` — a definition inside a
        conditional body is a different code shape, and a function whose
        definition the emitter must treat as conditional is a coverage hole in
        the corpus rather than a perturbation of an existing path;
      * it must not be a `Return` — a `return` under a guard makes every
        statement after it unreachable in the twin, so the twin's dead code
        becomes the thing being measured;
      * it is always a DIRECT child of a function body, never a nested
        statement, so no `break`/`continue` can end up captured by the guard.

    `while`/`for`/`try` bodies are simply never chosen, which is why the third
    restriction is about the CHOICE and not about the guard.
    """
    order = list(an.functions)
    rng.shuffle(order)
    for fn in order:
        if _is_constructor(an, fn):
            continue          # `_is_constructor`: the guard would change the
                               # CONSTRUCT, not the program's shape
        cands = [i for i, s in enumerate(fn.body)
                 if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef,
                                       ast.ClassDef, ast.Return,
                                       ast.Import, ast.ImportFrom))]
        if not cands:
            continue
        i = rng.choice(cands)
        guarded = ast.If(test=ast.Constant(value=True), body=[fn.body[i]],
                         orelse=[])
        ast.copy_location(guarded, fn.body[i])
        fn.body[i:i + 1] = [guarded]
        ast.fix_missing_locations(module)
        return module
    raise NotApplicable("no function body with a guardable statement")


# -- 6. `a + b` -> `b + a` ---------------------------------------------------

def t_swap_add(module, an, rng):
    """Exchange the operands of an integer `+`.

    SOUNDNESS.  Integer addition is commutative, so `a + b` and `b + a` are the
    same value — including in the backend, whose word arithmetic is
    `a + b mod 2^64`, and modular addition is commutative too.  The predicate
    is not "any `+`": `a + b` is NOT commutative for lists, tuples or dicts
    (`[1] + [2]` and `[2] + [1]` are different values), so both operands must be
    integer literals or names in `Analysis.int_only`, and `int_only` requires
    every store of the name to be an integer literal in one scope.
    """
    cands = [n for n in ast.walk(module)
             if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add)
             and _operand_ok(n.left, an) and _operand_ok(n.right, an)]
    if not cands:
        raise NotApplicable("no `+` with two integer operands")
    node = rng.choice(cands)
    node.left, node.right = node.right, node.left
    return module


def _operand_ok(node, an):
    return (_is_int_literal(node)
            or (isinstance(node, ast.Name) and node.id in an.int_only))


# -- 7. `x = e` + uses -> the expression -------------------------------------

def t_extract(module, an, rng):
    """Replace `x = e` and every later use of `x` with `e` itself.

    SOUNDNESS, and this is the transform with the most to get wrong:

      * `e` must be one of `+ - * & | ^` over names and integer literals.
        Those are exactly the operators that COMMUTE WITH THE WORD WRAP on this
        path (`EXTRACT_OPS` says which, and says why `<<`, `>>`, `%`, `//` and
        `/` are not): a formal value is one 64-bit word, so recomputing `e` at
        a use gives the same 64-bit value only for operations whose answer
        depends on nothing but the low 64 bits of their operands.  `+ - *` are
        modular operations and `& | ^` read only the low bits, so for them
        `wrap(wrap(a) op wrap(b)) == wrap(a op b)` exactly.  `a << 4` is the
        counter-example that keeps the table honest: `2**70 << 4` wraps to 0 and
        `-1 << 4` wraps to -16, so inlining a shift past a binding would move a
        word, and it is excluded rather than reasoned about;
      * every operand must be INVARIANT from the binding to the uses — see
        `_inv`, which is a positional condition and not "never assigned";
      * `x` must not be stored at or after the binding (`_frozen_from`), must
        not be a name a nested scope captures (`_captured_names`), and must not
        be a keyword-argument name or `main`;
      * the assignment must be a DIRECT child of a function body, so `x` is
        bound unconditionally and every read of it is dominated by it.

    The last two restrictions are what make the use substitution a renaming
    rather than an approximation: with `x` frozen from the binding onwards, every
    read after it reads that statement's value.

    Each use is replaced with a FRESH deep copy of `e`: an AST node cannot
    appear twice in one tree (a shared subtree is walked twice and the
    emitter's linearisation of it becomes its own idea), which is the same trap
    `test_ast_formal.py` has a case about.
    """
    cands = []
    for fn in an.functions:
        if _is_constructor(an, fn):
            continue          # `_is_constructor`: removing a statement from a
                               # body this path inlines changes the construct
        captured = _captured_names(fn)
        for i, stmt in enumerate(fn.body):
            if _extractable(fn, stmt, an, i, captured):
                cands.append((fn, i))
    if not cands:
        raise NotApplicable("no `x = a + b` whose operands never change")
    fn, i = rng.choice(cands)
    stmt = fn.body[i]
    xname = stmt.targets[0].id
    expr = stmt.value
    # Only the reads AFTER the binding, and there is a reason it has to be
    # spelled this way: `x` may have been stored EARLIER in the body, and a read
    # before the binding reads that earlier value, not this one.
    tail = fn.body[i + 1:]
    uses = []
    for stmt2 in tail:
        for o in ast.walk(stmt2):
            if (isinstance(o, ast.Name) and o.id == xname
                    and isinstance(o.ctx, ast.Load)):
                uses.append(o)
    if not uses:
        raise NotApplicable("a binding nothing reads after it")
    for occ in uses:
        parent = an.parent_of(occ)
        if parent is None:
            raise NotApplicable("a use outside the tree")
        if isinstance(parent, ast.Attribute) and parent.value is occ:
            raise NotApplicable("a use as an attribute's object")
        _replace_child(parent, occ, copy.deepcopy(expr))
    fn.body.pop(i)
    ast.fix_missing_locations(module)
    return module


#: The operators `t_extract` will inline, and the arithmetic reason.  The
#: backend's values are ONE 64-bit word, so "the same expression recomputed at
#: the use" is the same 64-bit value only for operations that commute with the
#: wrap:
#:
#:   + - *      wrap(a op b) == wrap(wrap(a) op wrap(b)), because modular
#:              addition and multiplication are the operations themselves.
#:   & | ^      the low 64 bits of a bitwise op depend on nothing but the low
#:              64 bits of its operands, so a wrapped operand gives the same
#:              answer as an unwrapped one.
#:   - ~ +      likewise: `wrap(-a) == -wrap(a)` and `wrap(~a) == ~wrap(a)`.
#:
#: The operators DELIBERATELY absent are the ones where the wrap changes the
#: answer, which is the whole content of this table:
#:
#:   <<   `(a << k) mod 2^64` is not `(a mod 2^64) << k` — the bits shifted out
#:        are gone either way, but the shift of the wrapped value counts from
#:        the other end.  `2**70 << 4` wraps to 0; `-1 << 4` wraps to -16.
#:   >>   `(-1) >> 1` is -1 and `(2**64 - 1) >> 1` is `2**63 - 1` — the two
#:        operands have the same 64 bits and different answers.
#:   %  // /   a remainder is not a function of the low 64 bits alone: `q` and
#:        `q + 2**63` are the same word and `q % d` and `(q + 2**63) % d`
#:        differ.  Truncating division is the same story.
EXTRACT_OPS = (ast.Add, ast.Sub, ast.Mult, ast.BitAnd, ast.BitOr, ast.BitXor)


def _extractable(fn, stmt, an, index, captured=frozenset()):
    if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
        return False
    target = stmt.targets[0]
    if not isinstance(target, ast.Name):
        return False
    if target.id in an.arg_keywords or target.id == "main":
        return False
    if target.id in captured:
        # A name a NESTED scope in this function captures is not a frame slot
        # this transform may delete.  Two things go wrong at once: the binding
        # disappears from the frame the closure was defined over, and the use
        # INSIDE the closure — which `ast.walk` descends into — would be
        # replaced by the expression, so the closure would read its operands at
        # CALL time instead of the value it captured.  Measured on the
        # `closures` mix, 7 of 20 programs, and the symptom was a printed
        # number moving rather than a crash.
        return False
    if target.id in _interpolated_names(an.module):
        # A use inside an f-string or t-string is SOURCE TEXT: replacing the
        # `Name` node in the tree does not replace the text `ast.unparse`
        # writes, so the binding is deleted and the surviving text reads a name
        # that no longer exists.  Measured on the `fstrings` mix, where `w3` is
        # printed only through `print(f'v={w3} ')`.
        return False
    if not _frozen_from(fn, an, index, target.id):
        return False
    expr = stmt.value
    if not isinstance(expr, ast.BinOp) or not isinstance(expr.op, EXTRACT_OPS):
        return False
    return (_inv(expr.left, an, fn, index)
            and _inv(expr.right, an, fn, index))


def _frozen_from(fn, an, index, name):
    """Whether `name` cannot be stored at or after `fn.body[index]`.

    The condition that makes `t_extract` a renaming rather than an
    approximation: with every store of `x` below the binding, every read above
    the join reads the binding's value.  "Stored exactly once" is also
    sufficient and is what the first version asked for — but the corpus declares
    every local up front (`w = 0` in the preamble) and then stores it again in
    the body, so that predicate was false for every program in every mix and the
    transform measured nothing at all.  The positional predicate reaches them.
    """
    for store in an.stores_of(name):
        if an.in_nested_scope(fn, store):
            return False
        at = an.statement_index(fn, store)
        # STRICTLY greater: the binding's own store is AT `index` and is the
        # binding, not a violation of it.  `>=` here made `_extractable` false
        # for every candidate in the corpus — the statement that binds `x` is
        # always a store of `x` — which is why `extract` skipped all 220
        # programs of the soundness probe before this was fixed.
        if at is None or at > index:
            return False
    return True


def _inv(node, an, fn, index):
    """An operand whose value cannot change between the binding and the use.

    The condition is POSITIONAL, and it has to be: "the operand is never
    assigned" is sound but unreachable on a corpus that declares every local up
    front (`w = 0` in the preamble is a store), so `extract` would skip every
    program. What is actually needed is "the operand does not change AFTER the
    binding", which is decidable:

      * every store of the operand must be inside `fn` — a store in a sibling
        function, or at module level, is not ordered against this statement;
      * none of them may be inside a scope nested in `fn`, because such a store
        happens when that scope is CALLED and nothing here orders it against
        the uses being inlined;
      * every one of them must sit in a `fn.body` statement whose index is
        below `index`, so the operand holds its last pre-binding value at the
        binding and at every use after it.

    A PARAMETER satisfies all three with no stores at all, which is why this
    reaches `def f(n): x = n + 1; …; print(x)`.  A loop counter does not: it is
    stored inside the loop, which is a statement at or after the binding.  And
    `x` itself is refused, which is not a conservatism but the transform's own
    limit: inlining `x = x + y` would leave `print(x)` as `print(x + y)`, where
    the `x` is the ALREADY-UPDATED one — the corpus's dominant `x = x & 0xFFFF`
    idiom is untransformable for that reason and not by accident.

    The recursion into a nested `+ - * & | ^` is sound by the same argument
    applied one level down, and it is what lets a statement whose right-hand
    side is `(w13 + w14) | 3` be inlined at all.
    """
    if _is_int_literal(node):
        return True
    if isinstance(node, ast.Name):
        for store in an.stores_of(node.id):
            if an.in_nested_scope(fn, store):
                return False
            at = an.statement_index(fn, store)
            if at is None or at >= index:
                return False
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, EXTRACT_OPS):
        return (_inv(node.left, an, fn, index)
                and _inv(node.right, an, fn, index))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub,
                                                              ast.UAdd,
                                                              ast.Invert)):
        return _inv(node.operand, an, fn, index)
    return False


# -- 8. reorder adjacent statements -----------------------------------------

class _Info:
    """Reads, writes, closure-visible names, control transfer and OBSERVABILITY
    of a statement — everything `t_reorder`'s independence test reads."""

    __slots__ = ("reads", "writes", "escapes", "terminal", "effectful")

    def __init__(self):
        self.reads = set()
        self.writes = set()
        self.escapes = set()
        self.terminal = False
        self.effectful = False


def _info(node, out=None, in_block=False):
    """`out` filled in for `node`, WITHOUT descending into nested scopes.

    `escapes` is what makes reordering subtle, and it is the reason this is not
    six lines: a name a NESTED function reads is not read when the statement
    runs, so `x = 1` before `def g(): …x` and after it are different programs
    even though neither statement mentions `g`.  Both the nested function's
    reads and its writes are collected, and either direction of a clash with the
    other statement's writes blocks the swap.

    `terminal` is asked about EVERY node including the statement itself, and it
    has to be: the most valuable pair in this corpus is `print(...)` beside a
    `return`, and a version that only classified CHILDREN reported that pair as
    swappable and produced a program that lost its return value.  Measured: 4 of
    30 programs on `metamorph`/`calls`, all of them this.
    """
    out = out if out is not None else _Info()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                         ast.ClassDef)):
        out.escapes |= _nested_names(node)
        # Observable too, and for a reason that is not obvious from the node:
        # a nested `def` whose body prints is an output channel, and whether the
        # two statements around it can be exchanged depends on whether anything
        # CALLS it between them.  Reading only the statement's own expression
        # would call a definition pure.
        out.effectful = True
        return out
    if isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom, ast.Raise,
                         ast.Await, ast.Global, ast.Nonlocal)):
        out.terminal = True
    elif isinstance(node, (ast.Break, ast.Continue)):
        # Terminal only when it is not inside a loop or `try` of its own: that
        # construct's exit label lives inside `node`, so the statement list is
        # still linear past it.  `in_block` is the answer, carried down.
        if not in_block:
            out.terminal = True
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load):
            out.reads.add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            out.writes.add(node.id)
            if isinstance(node.ctx, ast.Del):
                out.reads.add(node.id)
    elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        # An augmented assignment READS as well as writes; a swap that treats it
        # as a pure write inverts the order of a read and a write of the same
        # name, which is the single most likely way this transform could be
        # unsound.
        out.reads.add(node.target.id)
        out.writes.add(node.target.id)
    if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
        out.writes.add(node.target.id)
    if isinstance(node, (ast.Subscript, ast.Attribute)) and isinstance(
            node.ctx, (ast.Store, ast.Del)):
        # `L8[0] = 31` and `o.x = 1` WRITE the base, and they say so with a
        # `ctx` on the Subscript/Attribute rather than on a Name — so a reader
        # that only looks at Name nodes sees a statement that writes nothing and
        # will happily swap it with the `L8 = [0]` above it.  Measured on
        # `mmsound:2` of the `lists` mix: the oracle caught the swap as
        # `transform-invalid`.
        out.writes |= _names_in(node.value)
    if isinstance(node, ast.Call):
        # OBSERVABLE.  A call is the program's output channel — `print`, a
        # `read`, anything that reaches the outside world — and two observable
        # statements cannot be exchanged, because exchanging them exchanges the
        # order of the two lines of output they produce.  Measured: two adjacent
        # `print(…)` statements in `mmsound:2` of the `calls` mix, and the
        # oracle caught it as `transform-invalid` with one output line moved.
        #
        # "Contains a call" is a coarse over-approximation — a call to a pure
        # helper is not observable — and it is the right direction: it can only
        # refuse a swap, never license an unsound one.  A statement with no call
        # at all cannot touch anything outside the frame, which is what makes
        # an observable/pure pair swappable whenever the names are disjoint.
        out.effectful = True
    for child in ast.iter_child_nodes(node):
        _info(child, out, in_block or isinstance(node, (ast.For, ast.While,
                                                        ast.AsyncFor, ast.Try)))
    return out


def _nested_names(fn):
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
    return out


def _captured_names(fn):
    """The names a scope NESTED IN `fn` reads or writes.  `fn` excluded."""
    out = set()
    for n in ast.walk(fn):
        if n is fn:
            continue
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                          ast.ClassDef)):
            out |= _nested_names(n)
    return out


def _reachable_by_a_call(an, fn):
    """The names a CALL made from inside `fn` may read or write.

    Two hazards, one predicate, and neither is visible in the two statements
    being exchanged:

      * a CLOSURE CELL — `c = 9` beside `print(cf(4))` where `cf`, defined
        earlier, reads `c`.  Swapping them prints 5 instead of 13, because the
        closure reads the cell and the cell now holds the old value.  Measured,
        and caught by CPython as a `transform-invalid` before any build.  This is
        the hazard `formal_fuzz.py`'s `closures` mix was written to find,
        reached from the other direction;
      * a GLOBAL — `G = 57` beside `print(bump(2))` where `bump` declares
        `global G` and mutates it.  The two statements share no name, the call
        does not mention `G`, and swapping them changes the printed value.
        Measured on the `globals` mix, 2 of 30 programs, same verdict.

    So the set is "every name a module-level binding can be reached by" — which
    is every name bound in the MODULE scope, plus every name any scope nested in
    this function captures — and the rule is that a statement writing one of them
    is not exchanged with a statement that CALLS anything.  Coarser than the
    truth (a call to a function that touches no global is harmless), and sound:
    over-approximating reachability can only refuse a swap.
    """
    return set(an.module_bindings) | _captured_names(fn)


def t_reorder(module, an, rng):
    """Swap two adjacent statements of a function body that cannot interact.

    SOUNDNESS.  Two statements may be exchanged iff

      * neither reads a name the other writes, and neither writes a name the
        other reads or writes;
      * neither escapes through a nested function over the other's writes or
        reads;
      * neither can leave the block (`return`, `yield`, `raise`, `await`, or a
        `break`/`continue` not inside a loop or `try` of its own);
      * they are not BOTH observable — two statements that each print cannot be
        exchanged, because exchanging them exchanges two lines of output;
      * a statement that WRITES a name a call from this function can reach
        (`_reachable_by_a_call` — a module-level binding, or a name a nested
        scope captures) is not exchanged with a statement that calls anything.
        This is the rule no amount of looking at the two statements finds, and
        it carries the closure-cell and the global hazards at once.

    Every one of those is a decidable predicate, and the CPython oracle then
    checks the RESULT — but the predicate is the transform, and the oracle is the
    net under it.  A predicate that were wrong would show up as
    `transform-invalid`, which is reported as loudly as a backend bug, so the two
    checks cannot be confused.  Measured, all four of the rules above having been
    wrong at least once: 13 programs whose adjacent pair was two `print`s, two
    whose pair was `x = 0` beside `xs[0] = 1`, one closure program whose pair was
    `c = 9` beside the call that reads the cell, and two `globals` programs whose
    pair was `G = 57` beside a call that mutates `G` from another function.
    """
    pairs = []
    for fn in an.functions:
        infos = [_info(s) for s in fn.body]
        reach = _reachable_by_a_call(an, fn)
        for i in range(len(fn.body) - 1):
            a, b = infos[i], infos[i + 1]
            if a.terminal or b.terminal:
                continue
            if a.effectful and b.effectful:
                continue
            if a.writes & reach and b.effectful:
                continue
            if b.writes & reach and a.effectful:
                continue
            if _is_constructor(an, fn) and not (
                    _self_field_stores(fn.body[i])
                    and _self_field_stores(fn.body[i + 1])):
                # A constructor body is inlined at the construction site, so the
                # only reordering it survives is between two of the
                # `self.<field> = …` assignments it is made of.  Measured: the
                # refusal names the shape, and it fires for anything else.
                continue
            if a.writes & (b.reads | b.writes):
                continue
            if b.writes & (a.reads | a.writes):
                continue
            if a.writes & b.escapes or b.writes & a.escapes:
                continue
            if a.escapes & b.reads or b.escapes & a.reads:
                continue
            pairs.append((fn, i))
    if not pairs:
        raise NotApplicable("no adjacent independent pair")
    fn, i = rng.choice(pairs)
    fn.body[i], fn.body[i + 1] = fn.body[i + 1], fn.body[i]
    return module


# -- 9. definition order -----------------------------------------------------

def t_def_order(module, an, rng):
    """Permute a run of consecutive top-level definitions.

    SOUNDNESS.  A `def` binds its name when the `def` STATEMENT runs, and every
    body here runs later — from a later top-level statement, or from inside
    `main`, which is the corpus's last statement — so no name a body reads is
    unbound by the permutation, PROVIDED the permutation stays inside a RUN of
    consecutive definitions.  A run is the maximal stretch of the module body
    holding nothing but `def`s, so there is no top-level statement between the
    run's ends that could call one of them first.

    `class` bodies are excluded outright, and that is a deliberate narrowing
    rather than an oversight: a class body executes AT DEFINITION TIME, so a
    class reading a name a LATER class in the same run defines would break —
    and unlike a `def`, there is no moment after which it is safe.  A run of
    `class`es is therefore not permuted rather than permuted with a proof
    nobody re-reads.
    """
    body = module.body
    runs = []
    i = 0
    while i < len(body):
        if not isinstance(body[i], (ast.FunctionDef, ast.AsyncFunctionDef)):
            i += 1
            continue
        j = i
        while j < len(body) and isinstance(body[j], (ast.FunctionDef,
                                                     ast.AsyncFunctionDef)):
            j += 1
        runs.append((i, j))
        i = j
    runs = [(lo, hi) for lo, hi in runs if hi - lo > 1]
    if not runs:
        raise NotApplicable("no run of two or more definitions")
    rng.shuffle(runs)
    for lo, hi in runs:
        chunk = body[lo:hi]
        perm = list(range(len(chunk)))
        rng.shuffle(perm)
        if perm == sorted(perm):
            continue
        body[lo:hi] = [chunk[k] for k in perm]
        return module
    raise NotApplicable("every run was already in order")


# -- 10. inline a single-return helper ---------------------------------------

def t_inline_helper(module, an, rng):
    """Substitute a single-`return` function into every call of it.

    SOUNDNESS.  The callee's body must be EXACTLY one `return <expr>`, so calling
    it and inlining it differ only in whether a call frame exists; the
    arguments must be NAMES OR LITERALS, so substituting an argument that
    appears twice in the body cannot duplicate a side effect; the callee must
    not be RECURSIVE (inlining a recursive call never terminates); it must not
    be passed around as a VALUE, bound to a name, used as an attribute or used
    as a keyword name (only a call-shaped use is substituted); it must have no
    defaults, no `*args`, no `**kwargs` and no keyword-only parameters, so that
    arity is the only thing a call site varies; and the function must not be
    `main`, whose call the build's startup stub emits rather than the source.

    The substitution is a syntactic copy of the `return`'s expression, and the
    callee's body has no nested `def` to shadow a parameter inside it — that is
    what the "exactly one statement" restriction buys, and it is why the
    substitution may match parameter names by spelling.

    The substitution runs in ONE pass over the expression, collecting the
    occurrences of every parameter before replacing any of them.  One pass per
    parameter CAPTURES: `def f(a, b): return a * 10 + b` called as `f(b, 2)` in
    a caller that has its own `b` would substitute `a` first, insert a copy of
    the caller's `b`, and then substitute `b` everywhere — including into the
    copy it had just made.  Measured on the `closures` mix: 4 twins CPython
    could not run, all of them this.
    """
    cands = []
    for fn in an.functions:
        if fn.name == "main" or _is_recursive(fn):
            continue
        if len(fn.body) != 1 or not isinstance(fn.body[0], ast.Return):
            continue
        args = fn.args
        if args.vararg or args.kwarg or args.kwonlyargs:
            continue
        if any(d is not None for d in args.defaults):
            continue
        if _used_as_value(module, fn.name):
            continue
        all_calls = [n for n in ast.walk(module)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == fn.name]
        if not all_calls:
            continue
        params = [a.arg for a in _params(fn)]
        if any(len(c.args) != len(params) or c.keywords for c in all_calls):
            continue
        if not all(_is_plain_arg(a) for c in all_calls for a in c.args):
            continue
        cands.append((fn, params))
    if not cands:
        raise NotApplicable("no single-return helper called with plain "
                            "positional arguments")
    fn, params = rng.choice(cands)
    expr_template = fn.body[0].value
    sites = [n for n in ast.walk(module)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == fn.name]
    for call in sites:
        parent = an.parent_of(call)
        if parent is None:
            raise NotApplicable("a call outside the tree")
        expr = copy.deepcopy(expr_template)
        subst = dict(zip(params, call.args))
        # The occurrences are collected FIRST, so a copy inserted for one
        # parameter is not itself a candidate for the next one.  And the
        # parent index is built over the COPY: `an.parents` describes the
        # program's tree, and `expr` is a fresh subtree, so asking it for a
        # copy's parent answers None for every node and every substitution is
        # silently skipped.  Measured on the `closures` mix: 4 twins in which a
        # parameter was left unsubstituted, and CPython's
        # `NameError: name 'k11' is not defined` is what caught it.
        local = _parent_index(expr)
        targets = [(n, subst[n.id]) for n in ast.walk(expr)
                   if isinstance(n, ast.Name) and n.id in subst]
        for occ, repl in targets:
            occ_parent = local.get(id(occ))
            if occ_parent is None:
                raise NotApplicable("a parameter occurrence with no parent")
            _replace_child(occ_parent, occ, copy.deepcopy(repl))
        if not _replace_child(parent, call, expr):
            raise NotApplicable("a call this transform could not replace")
    ast.fix_missing_locations(module)
    return module


def _is_plain_arg(node):
    return isinstance(node, ast.Name) or _is_int_literal(node)


def _is_recursive(fn):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == fn.name for n in ast.walk(fn))


def _used_as_value(module, name):
    """Whether `name` appears anywhere other than as a call's callee."""
    for n in ast.walk(module):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == name:
            continue
        if isinstance(n, ast.Name) and n.id == name \
                and not isinstance(n.ctx, ast.Load):
            return True
        if isinstance(n, ast.Attribute) and n.attr == name:
            return True
        if isinstance(n, ast.keyword) and n.arg == name:
            return True
    return False


#: The transformations, in the order they are tried.  Every one that applies is
#: a pair to build; the order only decides which one a screen line names when
#: several are reported for one program.
TRANSFORMS = collections.OrderedDict([
    ("rename", t_rename),
    ("dead_local", t_dead_local),
    ("extra_param", t_extra_param),
    ("noop_loop", t_noop_loop),
    ("if_true", t_if_true),
    ("swap_add", t_swap_add),
    ("extract", t_extract),
    ("reorder", t_reorder),
    ("def_order", t_def_order),
    ("inline_helper", t_inline_helper),
])

TRANSFORM_NAMES = tuple(TRANSFORMS)


def wanted_transforms(args):
    """The transforms this run asks for, validated ONCE and up front.

    Validating inside `check_pair` raised `SystemExit` on a WORKER THREAD, where
    it does not stop the run and prints nothing useful — the pool swallowed it
    and the sweep reported a clean tally over no programs.
    """
    names = [t.strip() for t in (args.transforms.split(",") if args.transforms
                                 else TRANSFORM_NAMES) if t.strip()]
    bad = [n for n in names if n not in TRANSFORMS]
    if bad:
        raise SystemExit(f"ERROR: unknown transform(s) {', '.join(bad)}; the "
                         f"table is {', '.join(TRANSFORM_NAMES)}")
    return names

#: What each transformation is FOR, for `--list-transforms` and for the ledger.
#: A transform whose purpose nobody can state is a transform whose results
#: nobody can read.
TRANSFORM_WHY = {
    "rename": "the allocator and the frame-slot map see a different program "
              "with the same meaning",
    "dead_local": "one more slot, and one more store to a slot nothing reads",
    "extra_param": "a different argument count at the same call sites",
    "noop_loop": "loop prologue and exit paths that were never emitted",
    "if_true": "a block that must still be lowered as a block",
    "swap_add": "operand order, for an operator that is commutative here",
    "extract": "the same value with no slot to hold it",
    "reorder": "emission order, and the fall-through edge between two blocks",
    "def_order": "the module's emission order, which the labels follow",
    "inline_helper": "a call frame that does not exist, and a return value "
                     "computed in the caller",
}


# ── programs ────────────────────────────────────────────────────────────────
#
# Two sources, and the second is why this tool reaches a class of bug the first
# cannot: `formal/examples/*.mojo` are files a PERSON wrote, so their shapes are
# the ones a backend is most likely to get wrong, and there is no generator here
# that would produce them.
#
# The examples carry no `main`, so `example_program` synthesises one: a fixed
# argument tuple per positional parameter, drawn from a fixed table, and the
# results printed.  It is generated ONCE per example and appended to the text
# BEFORE any transformation, so it is not itself a metamorphic variable — a
# driver that differed between the two programs would make every comparison
# meaningless.  It is appended BEFORE `def_order` runs too, so the driver can be
# permuted along with everything else and a divergence is still a divergence.

# ── Mojo source → a source CPython's parser accepts ─────────────────────────
#
# The transforms rewrite CPython's `ast`, so a file that spells Mojo-only syntax
# cannot be transformed at all, and 11 of `formal/examples`' 52 files arrived at
# the sweep as `examples NOT measured` for exactly that reason.  That is a
# coverage hole in the ONE corpus whose programs a person wrote, and it is the
# corpus this tool's whole argument rests on ("their shapes are the ones a
# backend is most likely to get wrong").
#
# So a file CPython's parser declines is NORMALISED first: a textual, one-way
# rewrite of the spellings that carry nothing a run can observe, and of nothing
# else.  It is deliberately NOT a second implementation of the ten
# transformations — it never looks at a tree, it runs before a tree exists, and
# it is applied to the ORIGINAL, so P and T are written in the same dialect and
# the pair is still one program.  It also does NOT touch the generated corpus:
# `formal_fuzz.make_program` emits none of these spellings (see this file's
# "WHY CPYTHON'S OWN PARSER"), which is the property that made the choice of
# `ast` sound, and `normalise_mojo` returns its input unchanged when the input
# already parses, so the corpus provably goes through untouched.
#
# THE GATE THE CPYTHON ORACLE CANNOT SUPPLY, and why it is needed.  The
# per-pair oracle checks CPython(P) == CPython(T), which is what makes a
# transformation trustworthy — but normalisation moves BOTH sides together, so a
# rule that changed the meaning would be invisible to it.  The rewriting is
# therefore checked against the file it claims to be the same as, by the machine
# that has to be right about both: `check_pair` re-runs the VERBATIM file on
# every backend whenever a rule fired and requires the same answer
# (`NORMALISES-DIFFERLY-<arch>`), and refuses to measure an example whose
# verbatim spelling will not run at all.
#
# Each rule, and why removing it changes nothing a run can observe:
#
#   PROOF_DECORATORS  `@spec(…)`, `@require(…)`, `@ensure(…)` are read by the
#                     PROOF layer; the run-time path never sees them.  They have
#                     to be REMOVED rather than merely made parseable, because
#                     CPython would execute them and raise NameError on
#                     `spec`/`require`/`ensure` — so keeping them would trade a
#                     coverage hole for an oracle that cannot answer.  Measured:
#                     `count.mojo` built VERBATIM answers `0` on both backends,
#                     and so does the same file with its three annotation lines
#                     gone.
#   VAR_DECL          `var x = e` and `x = e` are one construct on this path.
#                     `formal/examples/vardecl.mojo` exists BECAUSE the two
#                     spellings behave identically here: its own comment calls
#                     the bare-assignment file its twin, and `threevar.mojo`
#                     passed where this one failed.
#   FN_DECL           `fn f(…)` and `def f(…)` are one function form here — there
#                     is no overload set, no `-> None` discipline and no
#                     ownership on this path.  Measured: `wide_recv.mojo` spells
#                     all four of its methods `fn` and builds and answers `4` on
#                     both backends, while 41 of the 52 examples spell `def`.
#
# NOT here, and said rather than guessed: `struct Point:`.  A Python `class`
# body of bare annotations has no attributes, so `p.get_y()` reads a name that
# was never assigned while the struct's field reads `0` — a real disagreement
# with CPython, produced by the translation rather than found by it.  Giving
# each field an initialiser is a judgement about what the struct's fields are
# worth, which is not a removal of syntax, so `wide_recv.mojo` stays unmeasured
# and `example_program` names the construct it could not remove.

#: `(name, pattern)`, applied in this order.  `re.MULTILINE` and a leading
#: `^[ \t]*` rather than a word-boundary match, because the point is to match a
#: STATEMENT and a comment may contain the word: `vardecl.mojo`'s own first line
#: is a comment whose text is "`var a = 1` is a `VarDecl`", and a rule that
#: rewrote inside it would corrupt prose into code.
PROOF_DECORATOR_RE = re.compile(r"^[ \t]*@(spec|require|ensure)\s*\(")
VAR_DECL_RE = re.compile(r"^([ \t]*)var[ \t]+", re.MULTILINE)
FN_DECL_RE = re.compile(r"^([ \t]*)fn[ \t]+", re.MULTILINE)

#: A decorator's arguments can wrap, and a rule that deleted only the first line
#: would leave the rest of it to be parsed as code.  So the removal is driven by
#: parenthesis depth: `@spec(` opens one, and the line ends at the one that
#: closes it — whichever line that is.
def _drop_proof_decorators(lines):
    """`lines` without the `@spec`/`@require`/`@ensure` lines; `(kept, count)`."""
    kept, depth, n = [], 0, 0
    for line in lines:
        if depth == 0 and PROOF_DECORATOR_RE.match(line):
            n += 1
            depth = line.count("(") - line.count(")")
            if depth <= 0:
                depth = 0
            continue
        if depth:
            # Inside a decorator's arguments: consume until they balance.  A
            # `)` inside a string in the arguments would confuse the count, and
            # the arity of that bug is a file CPython then declines — reported,
            # not shipped.
            depth += line.count("(") - line.count(")")
            depth = max(depth, 0)
            continue
        kept.append(line)
    return kept, n


#: Mojo's statement keywords, so a file the rules could not fix says WHICH one
#: stopped it.  CPython's own message for `struct Point:` is
#: "invalid syntax (<unknown>, line 1)" — true, and useless to the reader who
#: has to decide whether to teach this tool the construct.  A keyword this table
#: has already been taught to remove (and did not) is itself worth naming, so the
#: scan runs on the NORMALISED text rather than the original.
MOJO_STATEMENT_KEYWORDS = ("struct", "trait", "alias", "comptime", "raises",
                           "inout", "borrowed", "owned", "let", "var", "fn")

_STATEMENT_START_RE = re.compile(r"^([ \t]*)([A-Za-z_]\w*)", re.MULTILINE)


def _blocking_keyword(text):
    """The first Mojo statement keyword left in `text`, or `""`."""
    for m in _STATEMENT_START_RE.finditer(text):
        if m.group(2) in MOJO_STATEMENT_KEYWORDS:
            return m.group(2)
    return ""


def normalise_mojo(source):
    """`(text, notes, why)` for `source` in a dialect CPython's parser accepts.

    `text` is `None` when the rules were not enough, and then `why` names the
    construct — the keyword scan over the NORMALISED text first (`struct
    Point:`), because CPython's own message for it is "invalid syntax
    (<unknown>, line 1)", which is true and useless to whoever has to decide
    whether to teach this tool the construct; its SyntaxError text is the
    fallback.  `notes` names every rule that FIRED, and is empty for a file that
    already parsed — which is the generated corpus, always.  A caller that
    reports nothing when a note fired is a caller whose coverage number is a lie
    about a file it did not measure as written.

    The first `ast.parse` is what keeps this cheap and total: a file that parses
    is already in the dialect, so it is returned UNCHANGED rather than run
    through rules that have nothing to do, which is both faster and one fewer
    way for a rule to damage a file it was not written for.  The second one is
    the check that the rules were enough.
    """
    try:
        ast.parse(source)
    except (SyntaxError, ValueError):
        pass
    else:
        return source, (), None
    lines, notes = source.splitlines(keepends=True), []
    lines, n = _drop_proof_decorators(lines)
    if n:
        notes.append(f"proof decorators x{n}")
    text = "".join(lines)
    for name, rx in (("var declaration", VAR_DECL_RE),
                     ("fn declaration", FN_DECL_RE)):
        text, k = rx.subn(r"\1", text)
        if k:
            notes.append(f"{name} x{k}")
    try:
        ast.parse(text)
    except (SyntaxError, ValueError) as e:
        kw = _blocking_keyword(text)
        return None, tuple(notes), (
            f"Mojo-only syntax this normaliser does not remove: {kw!r}"
            if kw else f"CPython still declines it: {e}")
    return text, tuple(notes), None


#: The argument tuples the synthesised driver calls with, in order.  Small,
#: positive and fixed, because the driver is an OBSERVATION and not a generator:
#: its only job is to make the example's function produce visible output.
EXAMPLE_ARGS = (0, 1, 2, 3, 7, 11)

#: How many top-level functions an example's driver calls.  Bounded so a
#: twenty-function example does not become a twenty-hundred-line driver.
EXAMPLE_MAX_CALLS = 4

#: The input an example's own `main` is measured at.  `10` is the value
#: `test_x86_64_examples.py::DEFAULT_INPUT` already builds every example with, so
#: this is the image the rest of the suite builds rather than a new convention;
#: `EXAMPLE_INPUT_PAD` is `formal/model.py::entry_arg_values`'s own padding —
#: the unused argument registers read `0` at `_start` — so the CPython driver and
#: the binary agree on the parameters past the first without either of them
#: inventing a value.
EXAMPLE_INPUT = 10
EXAMPLE_INPUT_PAD = 0


def example_program(source):
    """Everything this run needs to measure one `formal/examples` file.

    A dict, because the record has more than a text and a reason to carry and a
    tuple of three would make every caller index it blind:

      `text`         what CPython and both backends are asked to run.  `None` when
                     the file is not measured at all, and then `reason` says why.
      `verbatim`     the source the normalisation did NOT touch, with the same
                     driver appended — the text `NORMALISES-DIFFERLY` compares
                     against, and `None` when no rule fired (which is every file
                     of the generated corpus and 41 of the 52 examples).
      `driver_args`  the argument list the CPython driver calls `main` with.
                     `""` for the ordinary `main()`, and `"10, 0"` for a
                     two-parameter entry point.
      `test_input`   the `-n` the image bakes in, or `None` to leave the image
                     the default one.  The input is BAKED (`formal/build.py`'s
                     `test_input`), so the two must be the same list or the
                     comparison is between two different programs.
      `notes`        what `normalise_mojo` rewrote; empty when it rewrote
                     nothing.
      `reason`       why this file is not measured, when it is not.

    Three shapes of entry point, and the third is why this returns a REASON
    rather than a text or a bare None:

      * the example already has a `main` taking no parameters — used VERBATIM.
        Synthesising a driver for it would either shadow the entry point or, for
        `formal/examples/twoparams.mojo`'s `def main(n: Int, m: Int)`, call it
        with the wrong arity and recurse forever: measured, and the symptom was
        a twin CPython could not run with no indication why;
      * the example's `main` takes ARGUMENTS — MEASURED, by giving the image the
        input its `main` will receive and the CPython driver the same values.
        The first version of this reported those two files as undrivable with a
        comment saying it needed the shared `formal_fuzz` harness threaded;
        `formal_fuzz.run_on` now takes the `test_input` its own `build` and its
        proof-layer sibling already took, and this is that thread;
      * the example has no `main` — one is synthesised from its top-level
        functions and the fixed argument table.

    A file no rule can make parseable comes back with `reason` naming the
    construct it could not remove (`normalise_mojo` passes the SyntaxError
    through), so `wide_recv.mojo`'s `struct` is reported rather than dropped.
    """
    text, notes, why = normalise_mojo(source)
    if text is None:
        return {"text": None, "verbatim": None, "driver_args": "",
                "test_input": None, "notes": notes, "reason": why}
    tree = ast.parse(text)
    mains = [n for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name == "main"]
    if mains:
        spec = mains[0].args
        npos = len(spec.posonlyargs) + len(spec.args)
        shape = (spec.vararg, spec.kwarg, spec.kwonlyargs,
                 [d for d in spec.defaults if d is not None])
        if not (npos or any(shape)):
            return {"text": text, "verbatim": source if notes else None,
                    "driver_args": "", "test_input": None, "notes": notes,
                    "reason": None}
        if any(shape):
            return {"text": None, "verbatim": None, "driver_args": "",
                    "test_input": None, "notes": notes,
                    "reason": "its own main takes *args, **kwargs, keyword-only "
                              "or defaulted arguments"}
        values = [EXAMPLE_INPUT] + [EXAMPLE_INPUT_PAD] * (npos - 1)
        return {"text": text, "verbatim": source if notes else None,
                "driver_args": ", ".join(str(v) for v in values),
                "test_input": ",".join(str(v) for v in values),
                "notes": notes, "reason": None}
    # No `main`.  A driver is synthesised from the top-level functions, and
    # parameterised ones come FIRST: a zero-parameter function is only called
    # when the file has none, because `print(f())` of a function returning
    # `None` prints the word `None` while the image has no such word, and
    # admitting it everywhere would manufacture a divergence in every example
    # that happens to own a nullary helper.  As a FALLBACK it costs exactly one
    # example on this tree (`ret42.mojo`, the only file whose every top-level
    # function is nullary).
    fns = [n for n in tree.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    simple = [n for n in fns
              if not (n.args.vararg or n.args.kwarg or n.args.kwonlyargs)
              and not any(d is not None for d in n.args.defaults)]
    withp = [n for n in simple if len(n.args.posonlyargs) + len(n.args.args)]
    chosen = (withp or simple)[:EXAMPLE_MAX_CALLS]
    if not chosen:
        return {"text": None, "verbatim": None, "driver_args": "",
                "test_input": None, "notes": notes,
                "reason": "no top-level function the fixed argument table fits"}
    driver = _driver(chosen)
    return {"text": text.rstrip("\n") + "\n" + driver,
            "verbatim": (source.rstrip("\n") + "\n" + driver) if notes else None,
            "driver_args": "", "test_input": None,
            "notes": notes, "reason": None}


def _driver(chosen):
    """The synthesised `main()` for `chosen`, as text.

    One function because it is built twice — once onto the normalised text and,
    when a normalising rule fired, once onto the verbatim text — and the whole
    value of that comparison is that the two drivers are the SAME calls.
    """
    lines = ["def main() -> Int:"]
    for node in chosen:
        npos = len(node.args.posonlyargs) + len(node.args.args)
        lines.append("    print({}({}))".format(
            node.name,
            ", ".join(str(EXAMPLE_ARGS[i % len(EXAMPLE_ARGS)])
                      for i in range(npos))))
    lines.append("    return 0")
    return "\n".join(lines) + "\n"


def program_texts(args):
    """The program records this run measures, in the order it prints them."""
    out = []
    if args.examples:
        stems = sorted(f[:-5] for f in os.listdir(args.examples)
                       if f.endswith(".mojo"))
        for stem in stems:
            with open(os.path.join(args.examples, stem + ".mojo")) as f:
                out.append((stem, example_program(f.read())))
    for i in range(args.start, args.start + args.count):
        text = F.make_program(args.seed, i, args.mix, tuple(args.stmts))
        out.append((f"{args.seed}:{i}:{args.mix}",
                    {"text": text, "verbatim": None, "driver_args": "",
                     "test_input": None, "notes": (), "reason": None}))
    return out


# ── one pair ────────────────────────────────────────────────────────────────

def _answer(res):
    """`(exit, stdout)` from a `formal_fuzz.run_on` result, or None."""
    if res.get("verdict") != "ok":
        return None
    return (res.get("rc"), res.get("stdout"))


def _compare_one(backend, base, twin, want):
    """Every verdict for one backend on one pair.  A list, deduped and ordered.

    Four comparisons, and the four-way split is the whole design:

      * the two IMAGES against each other — `METAMORPH`, the one no oracle can
        produce, because both answers come from the same meaning.  This is the
        finding, and it is the reason the tool exists;
      * one image REFUSING what the other lowered — `TWIN-DIVERGES`, a backend
        bug rather than a documented limit, because the twin BUILT, so the
        construct is representable and the machine that declined it is wrong
        about the program;
      * the TWIN against CPython when the ORIGINAL agrees with CPython —
        `MISMATCH`, and this one is this tool's own: the transform CHANGED the
        answer, which is what a register-allocation or frame-layout bug behind a
        rename or a reorder looks like;
      * the ORIGINAL against CPython — `DIVERGENCE`, which is
        `tools/formal_fuzz.py`'s subject with its own attribution table
        (`KNOWN_DIVERGENCES`, `neutralise`, `blame`), and which this tool does
        NOT re-derive.  Reporting it as a finding would put a second
        attribution table in this file and make every run re-file the
        documented ones: measured on `formal/examples/udivmod.mojo`, where `/`
        is integer division on this path and float division in CPython — a real
        disagreement with a bug doc that another round holds, which this tool
        has no business claiming and no honest way to neutralise.

    The dedupe matters for more than tidiness: `MISMATCH-arch` used to be
    appended once per side, so a screen line read
    `MISMATCH-X86+MISMATCH-X86+MISMATCH-ARM+MISMATCH-ARM` for one disagreement.
    """
    out = []
    arch = "X86" if backend == "x86_64" else "ARM"
    bv, tv = base.get("verdict"), twin.get("verdict")
    for v in (bv, tv):
        if v == "crash":
            out.append("CODEGEN-CRASH")
        elif v == "codegen-internal":
            out.append("CODEGEN-INTERNAL")
        elif v == "timeout":
            out.append("TIMEOUT")
    if out:
        return out
    if bv == "trapped" or tv == "trapped":
        return ["trapped"]
    b_ans, t_ans = _answer(base), _answer(twin)
    if b_ans is not None and t_ans is not None:
        if b_ans != t_ans:
            out.append("METAMORPH-" + arch)
    elif (b_ans is None) != (t_ans is None):
        out.append("TWIN-DIVERGES-" + arch)
    elif bv == "refusal" and tv == "refusal":
        # Both refusing is agreement only if the WORDS agree: the two machines
        # are one language implementation.  A transform that does not change
        # the program must not change the sentence.
        if F.fold_arch(base.get("diag", "")) != F.fold_arch(twin.get("diag", "")):
            out.append("REFUSAL-DIVERGES-" + arch)
    # `MISMATCH` means the TRANSFORM INTRODUCED the disagreement: the original
    # agreed with CPython and the twin does not.  A disagreement BOTH sides have
    # is `DIVERGENCE` — the original's, and `formal_fuzz.py`'s to attribute —
    # and reporting it as `MISMATCH` too made every documented divergence into a
    # fresh finding on every run: measured on the `strings` mix, where
    # `s[i]` is a byte rather than a one-character string
    # (`formal_fuzz.KNOWN_DIVERGENCES`), 17 of 20 programs arrived as
    # `MISMATCH-X86`.  With both sides wrong AND different the localisation is
    # still there, because `METAMORPH` above already says they differ.
    base_bad = b_ans is not None and (b_ans[0] != want[0] or b_ans[1] != want[1])
    twin_bad = t_ans is not None and (t_ans[0] != want[0] or t_ans[1] != want[1])
    if base_bad:
        out.append("DIVERGENCE-" + arch)
    elif twin_bad:
        out.append("MISMATCH-" + arch)
    return out


#: Verdicts in the order a screen line and the tally read them.  The first
#: match wins, so `METAMORPH` outranks `MISMATCH` (the metamorphic violation is
#: the one this tool exists to find and the one that needs no oracle) and both
#: outrank the boring ones.
#:
#: `NORMALISES-*` sits above every backend verdict on purpose.  It is the one
#: finding that invalidates the row it is printed on rather than describing it: if
#: the normalised file and the file as written do not answer alike, nothing
#: measured about that file — including every `match` — is a statement about the
#: file a reader has open.  So a reader meets it first.
SEVERITY = (
    "NORMALISES-DIFFERLY-X86", "NORMALISES-DIFFERLY-ARM",
    "METAMORPH-X86", "METAMORPH-ARM",
    "TWIN-DIVERGES-X86", "TWIN-DIVERGES-ARM",
    "MISMATCH-X86", "MISMATCH-ARM",
    "REFUSAL-DIVERGES-X86", "REFUSAL-DIVERGES-ARM",
    "CODEGEN-CRASH", "CODEGEN-INTERNAL",
    "transform-invalid", "transform-crash",
    "NORMALISES-UNCOMPARABLE",
    "DIVERGENCE-X86", "DIVERGENCE-ARM",
    "TIMEOUT", "trapped", "not-answerable", "match",
)

#: The verdicts that make a run FAIL.  Spelled out rather than derived from
#: `SEVERITY`, because `SEVERITY` is ordered by how much a reader cares and ends
#: with the three that are NOT findings — `TIMEOUT`, `trapped`, `not-answerable`
#: and `match` — and a rule that computed the set by subtraction put `match` in
#: it, which printed a screen line for every clean program.
#:
#: `DIVERGENCE-*` is deliberately absent: a disagreement the ORIGINAL already has
#: is `formal_fuzz.py`'s to attribute and this tool's to count.  See
#: `_compare_one`.
#:
#: `NORMALISES-UNCOMPARABLE` IS here, and the reason it is not a skip is that it
#: is a hole rather than a property of the program: the file could be measured
#: only by removing syntax, the removed spelling would not build, so nothing
#: established that the removal preserved anything.  A run that reported it as
#: "not applicable" would report a coverage loss as though it were a file with
#: nothing to do.
FINDING_VERDICTS = (
    "NORMALISES-DIFFERLY-X86", "NORMALISES-DIFFERLY-ARM",
    "METAMORPH-X86", "METAMORPH-ARM",
    "TWIN-DIVERGES-X86", "TWIN-DIVERGES-ARM",
    "MISMATCH-X86", "MISMATCH-ARM",
    "REFUSAL-DIVERGES-X86", "REFUSAL-DIVERGES-ARM",
    "CODEGEN-CRASH", "CODEGEN-INTERNAL",
    "transform-invalid", "transform-crash",
    "NORMALISES-UNCOMPARABLE",
)


def _worst(verdicts):
    for want in SEVERITY:
        for got in verdicts:
            if got == want:
                return want
    return verdicts[0] if verdicts else "match"


def check_pair(label, prog, index, args, tmpdir):
    """One program: build it, transform it, and compare every engine's answers.

    `prog` is the record `program_texts` built — the text to run, the driver
    arguments the CPython oracle calls `main` with, the `-n` baked into the
    image, and (when a normalising rule fired) the file as it was written.

    The ORDER is the tool's soundness argument, and it is not negotiable:

      0. if a rule fired, the VERBATIM file is built and run on every backend and
         must answer what the normalised one answers (`_normalisation`), because
         normalisation moves both sides of every later comparison together and
         no oracle downstream of it can see a mistake in it;
      1. parse, and analyse;
      2. CPython answers P.  If it cannot, the pair says nothing;
      3. for each transform, CPython answers T.  If CPython answers P and T
         DIFFERENTLY the transform is unsound, which is reported as
         `transform-invalid` and the pair is DISCARDED — before a single build,
         because every later verdict about it would be meaningless;
      4. only then are the backends asked, and each is asked about BOTH sides.

    Step 3 is also what keeps the metamorphic claim honest: the invariant
    "P and T answer the same" is only worth checking once the oracle has agreed
    that P and T are the same PROGRAM.
    """
    rec = {"label": label, "index": index, "verdict": "match", "transforms": {},
           "diverge": [], "notes": prog.get("notes", ()),
           "driver_args": prog["driver_args"]}
    text = prog["text"]
    argv = prog["driver_args"]
    tin = prog["test_input"]
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as e:
        rec["verdict"] = "skip:unparsable"
        rec["detail"] = str(e)[:160]
        return rec
    ref, perr = F.cpython_answer(text, tmpdir, f"m{index}p", argv)
    if not F.has_oracle(ref):
        rec["verdict"] = "not-answerable"
        rec["detail"] = perr or "CPython produced no answer"
        return rec
    want = (ref[0], ref[1])
    base = {b: F.run_on(b, text, tmpdir, f"m{index}p", test_input=tin)
            for b in args.backends}
    # The ORIGINAL's own disagreement with CPython, once per program rather than
    # once per transform: every twin inherits its parent's answer, so counting it
    # per twin would report one disagreement ten times.  It is `DIVERGENCE-*` and
    # not a finding — see `_compare_one` for why that split is the difference
    # between a second tool with its own attribution table and a duplicate of
    # `tools/formal_fuzz.py`'s.
    for b in args.backends:
        ans = _answer(base[b])
        if ans is not None and (ans[0] != want[0] or ans[1] != want[1]):
            rec["diverge"].append("DIVERGENCE-"
                                  + ("X86" if b == "x86_64" else "ARM"))
    # STEP 0, before any transform: did the NORMALISATION preserve the program?
    # It is here rather than inside `normalise_mojo` because only a build can
    # answer it, and because a tool that quietly measured a rewritten file and
    # reported the file's name would be claiming coverage it does not have.
    bad = _normalisation(prog, base, args, index, tmpdir)
    if bad:
        rec["verdict"] = _worst(bad)
        rec["detail"] = ("the normalised file answers differently from the file "
                         "as written: " + "; ".join(bad))
        rec["text"] = text
        return rec
    for tname in wanted_transforms(args):
        entry = _one_transform(rec, label, text, index, tname, want, args,
                               tmpdir, base, tin)
        rec["transforms"][tname] = entry
    verdicts = []
    for entry in rec["transforms"].values():
        verdicts += entry["verdict"].split("+")
    # The program's verdict is a FINDING or `match`, never a `DIVERGENCE-*`: a
    # divergence is carried by `rec["diverge"]` and counted from there.  It used
    # to be folded in as well, and the tally then counted it twice per program —
    # once as the verdict and once as the divergence — which printed
    # `DIVERGENCE-X86 34` for 17 programs.
    findings = [v for v in verdicts if v in FINDING_VERDICTS]
    if findings:
        rec["verdict"] = _worst(findings)
        bad = [f"{t}={e['verdict']}" for t, e in rec["transforms"].items()
               if e["verdict"] != "match"]
        rec["detail"] = "; ".join(bad) or rec["verdict"]
    return rec


def _normalisation(prog, base, args, index, tmpdir):
    """Verdicts for the file `normalise_mojo` rewrote; `[]` when it rewrote none.

    The per-pair CPython oracle cannot supply this one, and the reason is
    structural rather than a gap: normalisation moves P and T together, so a rule
    that changed the meaning would leave the oracle comparing a program with
    itself.  So the rewriting is checked against the file it claims to be the
    same as, BY THE MACHINE — the verbatim build, on every backend, against the
    normalised build's answer.

    Three shapes, and the third is why this returns a verdict rather than a
    bool:

      * nothing fired — the whole generated corpus, and 41 of the 52 examples.
        `[]`, with no build: the rule that the common case costs nothing is
        itself worth having, because a gate that built a second image per program
        would double the sweep to check nothing.
      * the verbatim file does not run — `NORMALISES-UNCOMPARABLE`.  A
        normalisation whose original cannot be built cannot be shown to preserve
        anything, so the program is not measured and says so, rather than
        contributing a coverage number nobody checked;
      * the two disagree — `NORMALISES-DIFFERLY-<arch>`.  The finding is in the
        NORMALISER or in the backend's treatment of the syntax the normaliser
        removed, and either way the file is not measured until it is explained.
    """
    verbatim = prog.get("verbatim")
    if not verbatim:
        return []
    out = []
    for b in args.backends:
        got = F.run_on(b, verbatim, tmpdir, f"m{index}v_{b}",
                       test_input=prog["test_input"])
        if _answer(got) is None:
            out.append("NORMALISES-UNCOMPARABLE")
            continue
        ans = _answer(base[b])
        if ans is not None and ans != _answer(got):
            out.append("NORMALISES-DIFFERLY-"
                       + ("X86" if b == "x86_64" else "ARM"))
    return out


def _one_transform(rec, label, text, index, tname, want, args, tmpdir, base,
                   test_input=None):
    """Apply one transform, check it against CPython, then against the images.

    A FRESH deep copy of the tree and a FRESH `Analysis` per transform: four of
    the ten mutate the tree in place, and a shared tree would mean the second
    transform is measured on a program the first one edited.  That is not a
    theoretical hazard — it is the difference between measuring `if_true` and
    measuring `if_true` applied on top of `reorder`.
    """
    skip = {"verdict": "skip:" + tname}
    try:
        tree = ast.parse(text)
        new = TRANSFORMS[tname](tree, Analysis(tree),
                                random.Random(f"{args.seed}:{index}:{tname}"))
        ttext = ast.unparse(new)
    except NotApplicable as e:
        skip["detail"] = str(e)
        return skip
    except (SyntaxError, ValueError, RecursionError, TypeError,
            AttributeError, IndexError, KeyError) as e:
        return {"verdict": "transform-crash",
                "detail": f"{type(e).__name__}: {e}"[:220],
                "text": text}
    if not isinstance(new, ast.Module) or not ttext.strip():
        skip["detail"] = "produced an empty module"
        return skip
    tref, terr = F.cpython_answer(ttext, tmpdir, f"m{index}_{tname}",
                                  rec.get("driver_args", ""))
    if not F.has_oracle(tref):
        return {"verdict": "not-answerable",
                "detail": terr or "CPython produced no answer for the twin",
                "text": text, "twin": ttext}
    if (tref[0], tref[1]) != want:
        return {"verdict": "transform-invalid",
                "detail": f"CPython says the original answers {want[0]}/"
                          f"{want[1]!r} and the twin {tref[0]}/{tref[1]!r}",
                "text": text, "twin": ttext}
    verdicts = []
    twins = {}
    for b in args.backends:
        twins[b] = F.run_on(b, ttext, tmpdir, f"m{index}_{tname}_{b}",
                            test_input=test_input)
        verdicts += _compare_one(b, base[b], twins[b], want)
    entry = {"verdict": "+".join(verdicts) or "match"}
    if entry["verdict"] != "match":
        entry["text"] = text
        entry["twin"] = ttext
        entry["detail"] = " | ".join(
            f"{b}: {_short(base[b])} vs {_short(twins[b])}"
            for b in args.backends)
    return entry


def _short(res):
    v = res.get("verdict")
    if v == "ok":
        return f"ok {res.get('rc')}/{res.get('stdout', '')[:40]!r}"
    return f"{v} {F.fold_arch(res.get('diag', ''))[:90]}"


# ── reporting ───────────────────────────────────────────────────────────────

ALWAYS = ("match", "not-answerable", "transform-invalid", "transform-crash",
          "DIVERGENCE-X86", "DIVERGENCE-ARM")


def report(rec):
    """One screen line, or the empty string for a program with nothing to say.

    A transform that did not APPLY is not something to say: every program skips
    most transforms (there is no single-`return` helper in a generated corpus to
    inline), so printing the skips turned a clean 600-pair sweep into 60 lines
    of noise and buried the one line that mattered.  The skip counts are in the
    summary table instead, where they are per transform rather than per program.
    """
    # A transform entry that consists only of `DIVERGENCE-*` is carrying the
    # ORIGINAL's disagreement, which the line already says once — printing it
    # nine times said nothing the reader did not have and made a clean sweep of
    # the `strings` mix 17 lines of the same sentence.
    def _inherited(entry):
        return all(v.startswith("DIVERGENCE-")
                   for v in entry["verdict"].split("+"))

    parts = [f"{t}={e['verdict']}" for t, e in rec["transforms"].items()
             if e["verdict"] != "match" and not e["verdict"].startswith("skip:")
             and not _inherited(e)]
    finding = any(v in FINDING_VERDICTS for v in rec["verdict"].split("+"))
    if not parts and not finding and not rec.get("diverge"):
        return ""
    tail = (" [" + "; ".join(parts) + "]") if parts else ""
    if rec.get("diverge"):
        # Printed even when the program has no finding of its own, and labelled
        # with the queue it is in, because a reader who sees `0 findings` and a
        # divergence line below has to know that it is not this tool's.
        return "{}: DIVERGENCE ({}){}".format(
            rec["label"], ", ".join(rec["diverge"]), tail)
    return "{}: {}{}".format(rec["label"], rec["verdict"], tail)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--count", type=int, default=40,
                    help="how many GENERATED programs to measure")
    ap.add_argument("-s", "--seed", default="metamorph", metavar="SEED",
                    help="the seed; program i is a pure function of "
                         "(seed, i, transform, label), as formal_fuzz's is of "
                         "(seed, i, mix)")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--seeds", default=None, metavar="A-B",
                    help="a contiguous index range, spelled this way because a "
                         "sweep is nearly always a range")
    ap.add_argument("--mix", default="core", choices=sorted(F.MIXES))
    ap.add_argument("--stmts", nargs=2, type=int, metavar=("LO", "HI"),
                    default=(5, 12))
    ap.add_argument("--examples", default=None, metavar="DIR",
                    help="also measure every *.mojo in DIR "
                         "(formal/examples), each with a synthesised main()")
    ap.add_argument("--backends", default="x86_64,arm64")
    ap.add_argument("--arch", choices=("x86_64", "arm64"), default=None,
                    help="one architecture; it WINS over --backends rather "
                         "than adding to it, because the two say the same "
                         "thing in different vocabularies")
    ap.add_argument("--transforms", default=None, metavar="A,B",
                    help="only these transformations, comma list; the default "
                         "is every one of them")
    ap.add_argument("--list-transforms", action="store_true",
                    help="what each transformation is for, and exit")
    ap.add_argument("-j", "--jobs", type=int, default=4)
    ap.add_argument("--work", default=os.path.join(HERE, ".tmp",
                                                   "formal_metamorph"))
    args = ap.parse_args()
    if args.list_transforms:
        for name, why in TRANSFORM_WHY.items():
            print(f"  {name:<14} {why}")
        return 0
    if args.arch:
        args.backends = [args.arch]
    else:
        args.backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    for b in args.backends:
        if b not in ("x86_64", "arm64"):
            print(f"ERROR: unknown backend {b!r}", file=sys.stderr)
            return 2
    if args.seeds:
        lo, _, hi = args.seeds.partition("-")
        args.start, last = int(lo), int(hi)
        args.count = last - args.start + 1
    if sys.version_info < (3, 10):
        print("ERROR: the formal backend needs python3 >= 3.10 "
              "(export PATH=/opt/homebrew/bin:$PATH first)", file=sys.stderr)
        return 2
    os.makedirs(args.work, exist_ok=True)
    wanted_transforms(args)          # refuse a misspelt name before any build

    progs = program_texts(args)
    undrivable = {label: prog["reason"] for label, prog in progs
                  if prog["text"] is None}
    started = time.time()
    counts = {}
    per_transform = {t: collections.Counter() for t in TRANSFORM_NAMES}
    findings = []
    normalised = {}
    live = [(lbl, p) for lbl, p in progs if p["text"] is not None]
    tmpdir = tempfile.mkdtemp(prefix="metamorph.", dir=args.work)
    try:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            recs = list(pool.map(
                lambda kv: check_pair(kv[0], kv[1], kv[2], args, tmpdir),
                [(lbl, p, i) for i, (lbl, p) in enumerate(live)]))
        for rec in recs:
            counts[rec["verdict"]] = counts.get(rec["verdict"], 0) + 1
            for tname, entry in rec["transforms"].items():
                per_transform.setdefault(tname, collections.Counter())[
                    entry["verdict"].split(":")[0]] += 1
            for v in rec.get("diverge", []):
                counts[v] = counts.get(v, 0) + 1
            if rec.get("notes"):
                normalised[rec["label"]] = list(rec["notes"])
            line = report(rec)
            if line:
                print(line, flush=True)
            if any(v in FINDING_VERDICTS
                   for v in rec["verdict"].split("+")):
                findings.append(rec)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    with open(os.path.join(args.work, "findings.json"), "w") as f:
        json.dump({"args": vars(args), "counts": counts,
                   "per_transform": {t: dict(c) for t, c in per_transform.items()},
                   "undrivable": undrivable, "normalised": normalised,
                   "findings": findings},
                  f, indent=1)
    if findings:
        outdir = os.path.join(args.work, "findings")
        os.makedirs(outdir, exist_ok=True)
        for n, rec in enumerate(findings):
            stem = "{}_{}".format(
                f"{n:03d}", re.sub(r"[^A-Za-z0-9_.-]", "_", rec["label"]))
            with open(os.path.join(outdir, stem + ".mojo"), "w") as f:
                f.write(rec.get("text") or "")
            for tname, entry in rec["transforms"].items():
                if entry.get("twin"):
                    with open(os.path.join(outdir,
                                           f"{stem}.{tname}.mojo"), "w") as f:
                        f.write(entry["twin"])
    elapsed = time.time() - started
    tried = sum(sum(c.values()) for c in per_transform.values())
    print(f"\nformal_metamorph seed={args.seed} mix={args.mix} "
          f"backends={','.join(args.backends)} programs={len(recs)} "
          f"pairs={tried} in {elapsed:.1f}s "
          f"({tried / max(elapsed, 0.01):.1f} pairs/s, jobs={args.jobs})")
    # The four that are a MEASUREMENT are always printed, zero included: "0
    # transform-invalid" is a fact about the tool and "no line" is not, and a
    # reader cannot tell a run that saw none from a run whose summary never
    # mentioned them.
    for v in ALWAYS:
        print(f"  {v:<20} {counts.get(v, 0)}")
    for v, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if v not in ALWAYS:
            print(f"  {v:<20} {n}")
    print("  transforms (skip = does not apply to that program):")
    for tname in TRANSFORM_NAMES:
        row = per_transform.get(tname) or {}
        print(f"    {tname:<14} "
              + (", ".join(f"{k}={v}" for k, v in sorted(row.items()))
                 or "(not attempted)"))
    if undrivable:
        by_reason = collections.Counter(undrivable.values())
        print(f"  examples NOT measured: {len(undrivable)}"
              + ("".join(f"\n    {n} x {why}" for why, n
                         in by_reason.most_common())))
        print("    " + ", ".join(sorted(undrivable)[:10])
              + (" ..." if len(undrivable) > 10 else ""))
    if normalised:
        # WHICH FILES were measured in a dialect this tool rewrote, and what it
        # rewrote.  Printed because "51 of 52 examples measured" reads as a fact
        # about the DIRECTORY, and 10 of those 51 were measured after a rule
        # fired — which is a smaller claim, and the reader is entitled to know
        # which ten.  Each of them was additionally checked against the file as
        # written (`NORMALISES-*`), so this is where the price of the rewrite is
        # stated rather than assumed.
        rules = collections.Counter(r for v in normalised.values() for r in v)
        print(f"  normalising rules fired on {len(normalised)} program"
              f"{'' if len(normalised) == 1 else 's'}; each was re-run on the "
              f"backends as written (`NORMALISES-*`):")
        for rule, n in sorted(rules.items()):
            print(f"    {rule} x{n}")
        print("    " + ", ".join(sorted(normalised)))
    print(f"findings written to {args.work}/findings.json "
          f"({len(findings)} program{'s' if len(findings) != 1 else ''})")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())