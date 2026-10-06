"""LOOP INVARIANTS AND VARIANTS, SYNTHESISED FROM THE LOOP'S OWN BODY.

WHAT THIS IS
------------
A counted loop's proof is three obligations and a variant:

    (init)   the invariant holds on entry;
    (step)   the invariant is preserved by one iteration;
    (post)   the invariant plus a false guard implies the postcondition;
    (var)    the variant is non-negative, and drops by at least 1 while the
             guard holds — which is what makes the loop terminate.

Until now this backend has had exactly one hand-written shape for that
(`_range_loop_pattern` in `formal/arm64_proof_gen.py`, one accumulator and one
`range` parameter) and a machine-level countdown contract. Everything else is
REFUSED by the semantic model: measured on `cd2a1678`, of twelve loop programs
covering the families below, the arm64 generator refuses eleven —

    model: ForStmt needs the generic loop contract            (count, product)
    model: a ListExpr has no value in the semantic model      (min/max, search,
                                                               fill, copy)
    model: this `while` loop's state is more than the one word (while + acc,
                                                               decreasing
                                                               measure, gcd,
                                                               collatz)

— and the twelfth, `for i in range(n): total += i`, emits a proof that Lean
REJECTS (`tools/formal_proof_census_baseline.json`: `sum_range` is
`lean-rejected`, 543 `native_decide` sites, `unsolved goals`). So no loop shape
in this corpus is proved today on either backend.

This module is the missing middle: it DERIVES a candidate invariant and a
candidate variant from the loop's transition relation, by linear algebra, and
discharges each obligation with the SAME tactic ladder
`formal/contracts.py::LADDER` reports. No per-example tactics, no example
named in the code, and a shape it cannot derive one for says so with the
reason rather than staying silent.

HOW A CANDIDATE IS DERIVED, AND WHY IT IS CORRECT
--------------------------------------------------
Read the loop's body as an affine map over its scalar variables:

    x' = A x + b

(`x` holds every parameter, every pre-loop local, the loop's counter and every
accumulator the body assigns; unchanged variables get an identity row and a
zero `b`). Then:

  * a linear functional `c . x` is an **invariant** when `cA = c` and `c . b = 0`
    — its value is literally unchanged by an iteration, so induction needs
    nothing else; and
  * it is a **variant** when `cA = c` and `c . b < 0` — its value drops by
    exactly `c . b` every iteration.

Both are computed, not guessed: `c` is a left eigenvector of `A` for the
eigenvalue 1, which over `Q` is one null-space computation
(`nullspace([Aᵀ − I ; bᵀ])` and `nullspace([Aᵀ − I])` intersected with the
half-space `c . b < 0`). That is why `count_acc`'s `-c + i` is found rather
than written down, and why `sum_acc` is honestly reported as having none:
`total += i` makes `A`'s `(total, i)` block `[[1,1],[0,1]]`, whose only
eigenvector for 1 is `(0,1)` with `c . b = 1 > 0`, so **no affine invariant
exists** — the closed form `n(n-1)/2` is quadratic and this layer's arithmetic,
deliberately linear, cannot state it. A loop with no candidate gets a verdict,
not a silence.

**BRANCHES AND NON-LINEAR STORES ARE HANDLED, NOT IGNORED.** A candidate is
admissible only if every variable it mentions is assigned a LINEAR form in
EVERY branch of the body, so a variant is still decreasing on the path that was
not read. That single rule is what keeps `min_scan`'s counter variant honest
while refusing to invent an invariant for its `best`: `i` is affine in both
branches, `best = a[i]` is a subscript and is not. When nothing survives, the
reason is the specific store — "the body's conditional store reads `a[i]`, a
subscript, which is not a linear form in the loop's scalar variables; the
invariant that would say more is a quantifier over the array, and this layer's
obligation language has no quantifier" — which is a thing the next reader can
act on and `UNKNOWN` alone is not.

WHY THE OBLIGATIONS ARE STATED OVER `Int`
-----------------------------------------
`formal/contracts.py` renders its theorems over `UInt64` with the sign-flip
spelling (`^^^ 0x8000…`) because a contract must talk about the machine's own
reading of a word. A loop invariant does not: it is a property of the SOURCE's
integer semantics, and this layer's whole content is arithmetic that
`formal/contracts.py::LADDER`'s `omega` is a decision procedure for. `omega`
has no arithmetic on `Fin (2^64)` — which is exactly why `bv_decide` is
deliberately absent from `LADDER` (`formal/contracts.py`'s own note) and why the
first version of these goals was rewritten: on a `UInt64` goal every rung
failed and the verdicts would have been UNKNOWN for a reason about word
arithmetic rather than about the loop.

So: `Int`, and an `Int` here is the SIGNED reading of the program's word, by
`formal/contracts.py::_signed`'s convention and `lib/ProofLib.lean`'s `sKey`.
That is a real convention and it is a real limit, so it is stated three times:
in this docstring, in the docstring of every emitted file, and in a row of
`test_formal_loop_invariants.py` that measures the Int model against CPython
AND against the built image on both architectures. A theorem about the Int
model is not a claim about the machine, and the difference is checked rather
than asserted.

THE LADDER IS THE SHARED ONE, IN A STATED ORDER
-----------------------------------------------
Every goal here is closed by `omega`, so the emitted `first | …` puts `omega`
first and `simp_all` after it. The rungs are `formal/contracts.py::LADDER`'s
and nothing else — `ladder_script` reads that tuple, so a rung added there is a
rung here, and `test_formal_loop_invariants.py` pins that the two SETS are
equal.

**The order is measured, not tidied.** With `simp_all` first, the one-step
obligation `c - i = 0 → c' - i' = 0` under `c' = c + 1`, `i' = i + 1` does not
close: `simp_all` NORMALISES `c' - i'` to `c - i` and reports success for the
simplification without closing the goal, so `first` never reaches `omega` and
Lean reports `unsolved goals` on a theorem that is true (measured, and it is
the first thing this module emitted). `omega` first closes it in 0.5 s. The
same order is what lets a WRONG candidate stay wrong: `omega` cannot prove a
false goal, so it reports a counterexample and the rung after it is never
reached.

WHAT IS REPORTED, AND WHAT IS NEVER REPORTED
--------------------------------------------
Per loop, per obligation: `PROVED` / `UNKNOWN` / `REFUTED`, always with a
sentence. A loop whose body is not affine gets a `no-candidate` obligation
that resolves to UNKNOWN naming the store that blocks it. A candidate that the
bounded search can violate is `REFUTED` with the input and the iteration that
violate it. Nothing here is `SKIPPED` for silence and nothing is `PROVED`
without Lean having closed the named theorem — the same rule
`formal/contracts.py::classify` states, and for the same reason.

THE BOUNDED SEARCH IS NOT A PROOF
---------------------------------
`refute` runs the loop's OWN body statements, read through
`formal/contracts.py`'s one expression IR and evaluated by its one evaluator,
from a finite set of entry values for a finite number of iterations. It is a
check, it is reported as one, and `PROVED` can only come from Lean.
"""

import os
import re
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fire_compiler as F  # noqa: E402

from formal import contracts as CT  # noqa: E402

# The verdict vocabulary is `formal/contracts.py`'s, imported rather than
# re-spelled, for the reason its own docstring gives: a typo in a verdict is a
# silent skip.
PROVED = CT.PROVED
REFUTED = CT.REFUTED
UNKNOWN = CT.UNKNOWN
SKIPPED = CT.SKIPPED

#: The largest absolute coefficient a synthesised candidate may carry. A
#: rational vector is turned into integers by clearing denominators, and a
#: loop whose eigenvector needs 10^9 is not one whose invariant a reader will
#: check by eye. The cap is what makes "the candidate is small enough to print"
#: a property of the search rather than a hope, and a vector over the cap is
#: reported as refused rather than silently dropped.
MAX_COEFF = 32

#: How many iterations the bounded search will simulate, and how many entry
#: values it will try. Both are the `formal/contracts.py` convention: a finite
#: set, reported as a finite set.
SEARCH_STEPS = 24
SEARCH_INPUTS = tuple(range(12))

#: The body's branches. A body with more ifs than this is reported rather than
#: expanded, because the expansion is exponential in the number and a layer
#: whose cost nobody bounded is not this layer.
MAX_BRANCHES = 16

#: The linter is silenced because these theorems name a loop's every variable,
#: and a `for` loop's step names the accumulators a particular candidate does
#: not mention. An unused binder is a warning from Lean's style checker, not a
#: fact about the obligation.
LEAN_PRELUDE = """set_option maxHeartbeats 200000
set_option linter.unusedVariables false
set_option linter.unusedSimpArgs false
"""


# ── affine forms ─────────────────────────────────────────────────────────────
#
# An affine form is `({name: Fraction}, Fraction)`: a linear part and a
# constant. One reader, over `fire_compiler`'s own nodes, for the guard, the
# body, the entry values and the return — so a claim about the loop's entry
# values and a claim about its return are two readings of ONE set of ASTs, and
# the four obligations per loop cannot disagree about what the loop says.

def _af_const(v):
    return ({}, Fraction(v))


def _af_add(p, q, sign=1):
    co = dict(p[0])
    for name, v in q[0].items():
        co[name] = co.get(name, Fraction(0)) + sign * v
    return (co, p[1] + sign * q[1])


def _af_scale(p, k):
    return ({n: v * k for n, v in p[0].items()}, p[1] * k)


def _af_is_const(form):
    return not form[0]


def affine_form(node, known):
    """`node` as `(form, None)`, or `(None, reason)` when it is not affine.

    `known` is the set of names the form is allowed to mention. A name outside
    it is a REFUSAL with that name in the message rather than a zero
    coefficient, because `total = total + i` read without `i` is `total`, and
    that is a different program's invariant.

    `//`, `%`, a subscript, a call and a conditional expression are all
    refused with the operator that refused them. That list is the layer's
    frontier, so it is published here in one place rather than discovered one
    store at a time.
    """
    kind = type(node).__name__
    if kind == "IntLiteral":
        raw = getattr(node, "value", None)
        if raw is None:
            try:
                raw = int(getattr(node, "raw", None), 0)
            except (TypeError, ValueError):
                return None, f"the IntLiteral {getattr(node, 'raw', None)!r}"
        return _af_const(raw), None
    if kind == "IdentExpr":
        name = getattr(node, "name", None)
        if name not in known:
            return None, f"the name {name!r} is not one of the loop's variables"
        return ({name: Fraction(1)}, Fraction(0)), None
    if kind == "UnaryOp":
        op = getattr(node, "op", None)
        if op == "-":
            form, why = affine_form(node.operand, known)
            return (None, why) if why else (_af_scale(form, -1), None)
        if op == "+":
            return affine_form(node.operand, known)
        return None, f"the unary operator {op!r}"
    if kind == "BinaryOp":
        op = getattr(node, "op", None)
        if op in ("+", "-"):
            left, wl = affine_form(node.left, known)
            if wl:
                return None, wl
            right, wr = affine_form(node.right, known)
            if wr:
                return None, wr
            return _af_add(left, right, 1 if op == "+" else -1), None
        if op == "*":
            # One factor must be a literal. `acc * (i + 2)` is affine;
            # `acc * i` is not, and that is the difference between the product
            # family getting a variant and an accumulator invariant.
            for lit, other in ((node.left, node.right),
                               (node.right, node.left)):
                if type(lit).__name__ == "IntLiteral":
                    form, why = affine_form(other, known)
                    if why:
                        return None, why
                    return _af_scale(form, Fraction(getattr(lit, "value"))), None
            return None, ("a product of two non-constant factors "
                          f"(`{_show_node(node.left)}` x "
                          f"`{_show_node(node.right)}`)")
        if op in ("/", "%"):
            return None, (f"the operator `{op}`, which is not a linear form "
                          f"(`{_show_node(node.left)}` {op} "
                          f"`{_show_node(node.right)}`)")
        if op in CT._COMPARISONS:
            return None, (f"the comparison `{op}`, which is a predicate and "
                          f"not a value")
        return None, f"the operator `{op}`"
    if kind in ("SubscriptExpr", "ListExpr"):
        what = ("a subscript read" if kind == "SubscriptExpr"
                else "a list literal")
        return None, (f"{what}, which is not a linear form in the loop's "
                      f"scalar variables")
    if kind == "TernaryExpr":
        return None, "a conditional expression, which is a selection and not a form"
    if kind == "CallExpr":
        return None, (f"a call to `{getattr(node.func, 'name', '?')}`, which "
                      f"has no linear form here")
    return None, f"the expression node `{kind}`"


def show_form(form, names, rename=None):
    """An affine form as Lean `Int` source, read left to right.

    Parenthesised throughout and never elided, because this text is the
    STATEMENT of a theorem a machine checks: `a - b` and `a - (b - c)` are one
    character apart and one `sorry` apart in what they say.

    `rename` maps a variable to the name it is spelled with HERE, which is how
    the unprimed and the primed form of one candidate are printed by the same
    code and so cannot disagree about the coefficient of a shared variable.
    """
    coef, const = form
    ren = rename or {}
    terms = []
    for name in sorted(coef, key=lambda n: (names.index(n) if n in names else 0, n)):
        v = coef[name]
        if not v:
            continue
        name = ren.get(name, name)
        if v == 1:
            terms.append(name)
        elif v == -1:
            terms.append(f"- {name}")
        else:
            terms.append(("" if v > 0 else "- ") + f"({v}) * {name}")
    if const or not terms:
        if const:
            terms.append(("" if const > 0 else "- ") + f"({abs(const)})")
        else:
            terms.append("0")
    if len(terms) == 1:
        return terms[0]
    return "(" + " + ".join(terms) + ")"


def show_lin(coeffs, names):
    """A synthesised coefficient vector as Lean `Int` source."""
    return show_form(({n: coeffs[i] for i, n in enumerate(names)
                       if coeffs[i]}, Fraction(0)), names)


# ── rational linear algebra ──────────────────────────────────────────────────

def nullspace(rows, cols):
    """A basis of `{c : c . rows = 0}` over `Q`, as column vectors.

    Gauss-Jordan with `Fraction` throughout, so the answer is EXACT: a variant
    search that rounded would report a decreasing measure that is not one.
    """
    a = [[Fraction(x) for x in row] for row in rows]
    m = len(a)
    pivots, r = [], 0
    for c in range(cols):
        piv = next((i for i in range(r, m) if a[i][c]), None)
        if piv is None:
            continue
        a[r], a[piv] = a[piv], a[r]
        pv = a[r][c]
        a[r] = [x / pv for x in a[r]]
        for i in range(m):
            if i != r and a[i][c]:
                f = a[i][c]
                a[i] = [x - f * y for x, y in zip(a[i], a[r])]
        pivots.append(c)
        r += 1
        if r == m:
            break
    basis = []
    for free in [c for c in range(cols) if c not in pivots]:
        vec = [Fraction(0)] * cols
        vec[free] = Fraction(1)
        for i, c in enumerate(pivots):
            vec[c] = -a[i][free]
        basis.append(vec)
    return basis


def primitive(vec, cap=MAX_COEFF):
    """A rational vector as small integers, or None when it will not fit.

    Dividing through by the gcd is what turns `(1/2, 1/2)` into `(1, 1)` and
    `(1, -1)` into `(-1, 1)` depending on the sign; the sign is fixed by
    `flip` so the printed candidate reads the way a reader writes it.
    """
    den = 1
    for x in vec:
        d = x.denominator
        den = den * d // _gcd(den, d)
    ints = [int(x * den) for x in vec]
    g = 0
    for x in ints:
        g = _gcd(g, abs(x))
    if g == 0:
        return None
    ints = [x // g for x in ints]
    if max(abs(x) for x in ints) > cap:
        return None
    return ints


def flip(vec):
    """The same vector with its first nonzero coefficient positive.

    `c . x` and `-c . x` are both invariant, both variants, and only one of
    them reads like something a person would write. Applied once, to the first
    nonzero coefficient, so the choice is a function of the vector and not of
    the order the solver happened to return components in.
    """
    for x in vec:
        if x:
            return [-y for y in vec] if x < 0 else list(vec)
    return list(vec)


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return abs(a)

# ── the loop, as this layer needs it ─────────────────────────────────────────

class LoopShape:
    """One loop, read once, with everything the four obligations need.

    Deliberately a plain class with `__slots__` and no behaviour beyond
    `describe`: the obligations are built from its FIELDS, and a field that is
    computed here cannot be computed differently by the invariant side and the
    variant side.

      fn        the FunctionDef it came from
      index     its position in `fn.body`, so the report can point at it
      kind      "for-range" or "while"
      loop      the ForStmt / WhileStmt itself
      guard     the loop test, as an AST node (`i < stop`, `i != 0`, ...)
      body      the body's statements, as written
      target    the `for` target's NAME, or None for a `while`
      stop      the `range` stop expression for a `for`, or None
      start     the `range` start expression, or None
      names     the scalar variables, in a fixed order: parameters, pre-loop
                locals, the counter, the body's assignments
      init      `{name: AST node}`, each variable's value ON ENTRY. A
                parameter's own name stands for the parameter.
      updates   `{name: form}` for the variables assigned on EVERY branch, in
                each branch's own linear form. A variable assigned a
                non-linear form on any branch is ABSENT, which is what makes a
                candidate mentioning it inadmissible (see `admissible`)
      changes   the names `updates` mentions, i.e. what the loop moves
      blocked   `{name: reason}` for each variable a branch assigns a
                non-linear form to, so the report can NAME the store
      branches  how many straight-line paths the body has
      post      the `return` expression, or None
      unusable  a sentence when the loop cannot be read at all, else None
    """

    __slots__ = ("fn", "index", "kind", "loop", "guard", "body", "target",
                 "stop", "start", "stop_step", "names", "init", "updates",
                 "changes", "blocked", "branches", "post", "unusable")

    def __init__(self, **kw):
        for slot in self.__slots__:
            setattr(self, slot, kw.get(slot))

    @property
    def usable(self):
        return self.unusable is None

    def describe(self):
        if self.unusable:
            return f"a {self.kind} loop that cannot be read: {self.unusable}"
        guard = _show_node(self.guard)
        kind = "for" if self.kind == "for-range" else "while"
        return f"{kind} {guard}" + (f"  (changing {', '.join(self.changes)})"
                                    if self.changes else "")

    def __repr__(self):
        return f"LoopShape({self.kind}, {self.describe()!r})"


def _show_node(node):
    """An AST node as the source spelled it, for a report sentence.

    A message that says "the body's conditional store reads `a[i]`" is a
    message a reader can act on; one that says "a SubscriptExpr" is not, and
    the sweep's own cause table exists because the second kind of message is
    what makes 148 files read as "nobody has looked".
    """
    if node is None:
        return "<none>"
    kind = type(node).__name__
    if kind == "IdentExpr":
        return getattr(node, "name", "?")
    if kind == "IntLiteral":
        raw = getattr(node, "raw", "") or ""
        return raw if raw else str(getattr(node, "value", "?"))
    if kind == "AssignStmt":
        return (f"{_show_node(node.target)} = {_show_node(node.value)}")
    if kind == "AugAssignStmt":
        return (f"{_show_node(node.target)} {getattr(node, 'op', '?')}= "
                f"{_show_node(node.value)}")
    if kind == "VarDecl":
        return f"{getattr(node, 'name', '?')} = {_show_node(node.value)}"
    if kind == "UnaryOp":
        return f"{getattr(node, 'op', '?')}{_show_node(node.operand)}"
    if kind == "BinaryOp":
        return (f"{_show_node(node.left)} {getattr(node, 'op', '?')} "
                f"{_show_node(node.right)}")
    if kind == "SubscriptExpr":
        return f"{_show_node(node.obj)}[{_show_node(node.index)}]"
    if kind == "CallExpr":
        args = ", ".join(_show_node(a) for a in (getattr(node, "args", None) or []))
        return f"{getattr(node.func, 'name', '?')}({args})"
    if kind == "TernaryExpr":
        return (f"{_show_node(node.then_val)} if {_show_node(node.condition)} "
                f"else {_show_node(node.else_val)}")
    if kind == "IfStmt":
        return f"if {_show_node(node.condition)}"
    return kind


def _branches_of(body):
    """The body's straight-line paths, and why it has no such decomposition.

    Every top-level `if` doubles the path count, which is the right treatment
    rather than the convenient one: a candidate that is preserved on the `then`
    path and not on the `else` path is not an invariant, and a variant that
    decreases on one path only is not a variant. `MAX_BRANCHES` bounds the
    expansion, and a body that needs more says so instead of quietly
    assuming the `then` path.
    """
    plans = [[]]
    for st in body:
        kind = type(st).__name__
        if kind == "IfStmt":
            arms = [list(getattr(st, "then_body", None) or [])]
            elifs = list(getattr(st, "elifs", None) or [])
            for _cond, sub in elifs:
                arms.append(list(sub or []))
            if getattr(st, "else_body", None):
                arms.append(list(st.else_body))
            else:
                arms.append([])
            nxt = []
            for plan in plans:
                for arm in arms:
                    nxt.append(plan + arm)
            if len(nxt) > MAX_BRANCHES:
                return None, (f"the body branches more than {MAX_BRANCHES} "
                              f"ways and this layer bounds the expansion")
            plans = nxt
            continue
        for plan in plans:
            plan.append(st)
    # Checked AFTER the expansion, because an `if` arm's statements are
    # appended wholesale and a `return` inside one of them is exactly the shape
    # this rule is about — `lin_search.mojo` is that program.
    for plan in plans:
        for st in plan:
            kind = type(st).__name__
            if kind in ("BreakStmt", "ContinueStmt", "ReturnStmt",
                        "WhileStmt", "ForStmt"):
                word = {"ReturnStmt": "return", "BreakStmt": "break",
                        "ContinueStmt": "continue"}.get(kind, "a nested loop")
                return None, (f"the body contains a `{word}`, and a candidate "
                              f"over a loop body that leaves it early is a "
                              f"claim about the leaving path, which this layer "
                              f"does not make")
    return plans, None


def _scalar_updates(plan, known):
    """`(updates, blocked)` for one straight-line path.

    An assignment whose right-hand side is not a linear form does not BLOCK the
    path: it blocks its TARGET, and the target's own incoming value is then
    unknown. That is the distinction that lets `min_scan`'s counter keep a
    variant while its `best` loses its invariant, and it is why `blocked` is a
    per-path observation rather than a per-loop one.
    """
    updates, blocked, tainted = {}, {}, set()
    for st in plan:
        kind = type(st).__name__
        if kind in ("AssignStmt", "VarDecl"):
            target = getattr(st, "target", None) if kind == "AssignStmt" \
                else F.IdentExpr(getattr(st, "name", None))
            if type(target).__name__ != "IdentExpr":
                blocked.setdefault("<a non-name target>",
                                   f"a store to a {type(target).__name__}")
                continue
            name, value = target.name, getattr(st, "value", None)
        elif kind == "AugAssignStmt":
            target = getattr(st, "target", None)
            if type(target).__name__ != "IdentExpr":
                blocked.setdefault("<a non-name target>",
                                   f"a store to a {type(target).__name__}")
                continue
            name = target.name
            base = F.IdentExpr(name)
            op = {"+=": "+", "-=": "-", "*=": "*"}.get(getattr(st, "op", None))
            if op is None:
                blocked[name] = (f"the augmented operator `{st.op!r}` "
                                 f"`{name} {st.op}= …`")
                continue
            value = F.BinaryOp(op, base, getattr(st, "value", None), 0, 0)
        else:
            blocked.setdefault(f"<the statement {kind}>",
                               f"the statement `{kind}`")
            continue
        form, why = affine_form(value, known | tainted)
        if why:
            blocked[name] = f"`{_show_node(st)}` — {why}"
            tainted.add(name)
            continue
        read = [n for n in form[0] if n in tainted]
        if read:
            # The target is assigned a form, but it is a form over a name whose
            # own value on THIS path is unknown — so the target's value is
            # unknown too, and saying so is the difference between naming the
            # real obstacle (`y = t` where `t = x % y`) and naming a
            # consequence of it.
            blocked[name] = (f"`{_show_node(st)}` reads "
                             f"{', '.join(repr(r) for r in sorted(read))}, "
                             f"whose value on this path is not a linear form")
            tainted.add(name)
            continue
        updates[name] = form
    return updates, blocked


def loop_shapes(fn):
    """Every loop in `fn`, read; and the ones this layer cannot read, said.

    Only TOP-LEVEL loops are read, because the obligation language here is one
    iteration of one loop and a nested loop's counter is an outer-loop variable
    whose entry value depends on the outer iteration. A loop in an `if` or
    inside another loop is returned with `unusable` naming why, so the report
    counts it rather than forgetting it — `nested_loop.mojo` is in the corpus
    and its inner `while j != i` must appear somewhere other than nowhere.
    """
    out = []
    params = [p[0] for p in (getattr(fn, "params", None) or [])]
    names = list(params)
    init = {p: p for p in params}
    for index, st in enumerate(getattr(fn, "body", None) or []):
        kind = type(st).__name__
        if kind in ("ForStmt", "WhileStmt"):
            shape = _read_loop(fn, index, st, names, init)
            out.append(shape)
            # A loop's target and the names it assigns join the SCOPE of
            # everything after it, so a second loop in the same function reads
            # its predecessor's writes as its entry values.
            if shape.usable:
                for nm in shape.updates:
                    if nm not in names:
                        names.append(nm)
                        init.setdefault(nm, nm)
            continue
        if kind == "IfStmt":
            for sub, _label in _if_paths(st):
                out.extend(_nested_loops(sub, fn, index))
            continue
        nm = None
        if kind == "AssignStmt" and type(st.target).__name__ == "IdentExpr":
            nm = st.target.name
        elif kind == "VarDecl" and isinstance(getattr(st, "name", None), str):
            nm = st.name
        if nm is not None:
            if nm not in names:
                names.append(nm)
            init[nm] = getattr(st, "value", None)
    return out


def _if_paths(st):
    arms = [("then", list(getattr(st, "then_body", None) or []))]
    for cond, sub in (getattr(st, "elifs", None) or []):
        arms.append((f"elif {_show_node(cond)}", list(sub or [])))
    if getattr(st, "else_body", None):
        arms.append(("else", list(st.else_body)))
    return arms


def _nested_loops(stmts, fn, index):
    """Loops inside an arm or another loop, each carried as unusable."""
    out = []
    for st in stmts:
        kind = type(st).__name__
        if kind in ("ForStmt", "WhileStmt"):
            out.append(LoopShape(
                fn=fn, index=index, kind="for" if kind == "ForStmt" else "while",
                loop=st, guard=None, body=[], names=[], init={}, updates={},
                changes=[], blocked={}, branches=0, post=None,
                unusable=(f"it is nested inside another statement (`{kind}`), "
                          f"and one iteration of an inner loop is not one "
                          f"iteration of the outer one this layer's "
                          f"obligations are about")))
        elif kind == "IfStmt":
            for _label, sub in _if_paths(st):
                out.extend(_nested_loops(sub, fn, index))
        elif kind in ("WhileStmt",):
            out.extend(_nested_loops(getattr(st, "body", None) or [], fn, index))
        elif kind == "ForStmt":
            out.extend(_nested_loops(getattr(st, "body", None) or [], fn, index))
    return out


def _read_loop(fn, index, st, names, init):
    """One loop, read.  `LoopShape(unusable=…)` when it cannot be."""
    kind = "for-range" if type(st).__name__ == "ForStmt" else "while"
    shape = LoopShape(fn=fn, index=index, kind=kind, loop=st, guard=None,
                      body=list(getattr(st, "body", None) or []), target=None,
                      stop=None, start=None, names=list(names), init=dict(init),
                      updates={}, changes=[], blocked={}, branches=0, post=None,
                      unusable=None)
    if kind == "for-range":
        why = _read_for_range(st, shape)
        if why:
            shape.unusable = why
            return shape
    else:
        if getattr(st, "else_body", None):
            shape.unusable = ("the loop has an `else` clause, whose runs are "
                              "not this layer's obligations")
            return shape
        shape.guard = st.condition
        if shape.guard is None:
            shape.unusable = "the loop has no condition"
            return shape
    plans, why = _branches_of(shape.body)
    if why:
        shape.unusable = why
        return shape
    shape.branches = len(plans)
    # A `for` loop's step is the COUNTER's own increment, read from the shape
    # rather than appended to the body: `for i in range(a, b)` binds `i = a`
    # and then advances it, and appending a synthetic assignment would make the
    # body's own statements and the loop's semantics two different programs.
    known = set(shape.names)
    if kind == "for-range" and shape.target not in known:
        known.add(shape.target)
        shape.names.append(shape.target)
        shape.init[shape.target] = shape.start
    per_path = []
    for plan in plans:
        updates, blocked = _scalar_updates(plan, known)
        if kind == "for-range":
            step, w = affine_form(shape.stop_step, known)
            if w:
                shape.unusable = f"the loop's step: {w}"
                return shape
            updates[shape.target] = _af_add(
                ({shape.target: Fraction(1)}, Fraction(0)), step)
            blocked = {k: v for k, v in blocked.items() if k != shape.target}
        per_path.append((updates, blocked))
    common = set(per_path[0][0])
    for upd, _ in per_path[1:]:
        common &= set(upd)
    shape.updates = {nm: per_path[0][0][nm] for nm in sorted(common)}
    for _upd, blocked in per_path:
        for nm, why_b in blocked.items():
            shape.blocked.setdefault(nm, why_b)
    shape.changes = sorted(shape.updates)
    if not shape.updates:
        shape.unusable = ("the body assigns no variable a linear form in every "
                          "branch, so there is nothing to be an invariant over"
                          + (f" — {shape.blocked.get(sorted(shape.blocked)[0])}"
                             if shape.blocked else ""))
        return shape
    shape.post = _return_value(stmt for stmt in (fn.body[index + 1:]
                                                 if index + 1 < len(fn.body) else []))
    if shape.post is None:
        shape.unusable = ("the loop is not followed by a `return`, and the "
                          "postcondition is a statement about what the loop "
                          "leaves behind")
        return shape
    return shape


def _return_value(stmt):
    for st in stmt:
        if type(st).__name__ == "ReturnStmt":
            return getattr(st, "value", None)
    return None


def _read_for_range(st, shape):
    """`for target in range(...)`: the guard, the counter's entry and its step."""
    it = getattr(st, "iterable", None)
    args = list(getattr(it, "args", None) or [])
    name = getattr(getattr(it, "func", None), "name", None)
    if name != "range" or getattr(it, "kwargs", None):
        return (f"the loop iterates `{name}` and this layer's obligations are "
                f"about `range`")
    if len(args) == 1:
        start, stop = F.IntLiteral(0, 0, 0), args[0]
    elif len(args) == 2:
        start, stop = args[0], args[1]
    elif not args:
        return "`range()` with no argument"
    else:
        return f"`range` with {len(args)} arguments and no step argument"
    target = getattr(st, "target", None)
    if not isinstance(target, str):
        return f"the loop's target is a {type(target).__name__} and not a name"
    shape.target = target
    shape.start = start
    shape.stop = stop
    shape.stop_step = F.IntLiteral(1, 0, 0)
    shape.guard = F.BinaryOp("<", F.IdentExpr(target), stop)
    if getattr(st, "else_body", None):
        return "the loop has an `else` clause"
    return None


# ── synthesis ────────────────────────────────────────────────────────────────
#
# A candidate is a linear form over the loop's variables, and the whole
# synthesis is two null-space computations against the loop's transition
# relation. `build_relation` is the only place the relation is built, so the
# invariant side and the variant side cannot read two different `A`s.

class Relation:
    """The loop's `x' = A x + b`, over `names`.

    `names` is the loop's SCALAR variables, in the fixed order `shape.names`
    gives: a parameter, a pre-loop local, the counter, then the body's
    assignments sorted. A variable the body never assigns keeps an identity row
    and a zero constant, which is what puts the parameters into the space the
    candidates live in — and that is why the textbook `bound - counter` is
    FOUND rather than special-cased.
    """

    __slots__ = ("shape", "names", "changes", "A", "b", "index", "outside")

    def __init__(self, shape):
        self.shape = shape
        # A variable whose update form mentions a name the relation cannot see
        # is outside the relation TOO, and to a fixpoint -- `gcd_loop`'s
        # `x = y` mentions `y`, which `y = t = x % y` blocks, so `x` is blocked
        # and the loop has nothing left. Computing this once instead of
        # dropping the unnameable coefficient inside `Relation.transposed_shift`
        # would leave an all-zero row where the loop's own one lives, and a
        # candidate derived from that is decreasing for a transition the program
        # does not perform.
        outside = set(shape.blocked)
        while True:
            grown = set(outside)
            for nm, form in shape.updates.items():
                if nm in outside:
                    continue
                if set(form[0]) & outside:
                    grown.add(nm)
            if grown == outside:
                break
            outside = grown
        self.outside = outside
        self.names = [n for n in shape.names if n not in outside]
        self.changes = [n for n in shape.names
                        if n in shape.updates and n not in outside]
        self.index = {n: i for i, n in enumerate(self.names)}
        k = len(self.names)
        self.A = [[Fraction(1 if i == j else 0) for j in range(k)]
                  for i in range(k)]
        self.b = [Fraction(0)] * k
        for nm in self.changes:
            i = self.index[nm]
            coef, const = shape.updates[nm]
            self.A[i] = [Fraction(0)] * k
            for other, v in coef.items():
                if other not in self.index:
                    continue
                self.A[i][self.index[other]] = v
            self.b[i] = const

    def cols_of(self, coeffs):
        """A candidate's dictionary -> this relation's vector, or None."""
        try:
            return [Fraction(coeffs.get(n, 0)) for n in self.names]
        except TypeError:
            return None

    def dot(self, vec):
        return sum((vec[i] * self.b[i] for i in range(len(self.b))), Fraction(0))

    def at_i(self):
        """`(Aᵀ − I)`, the rows a candidate must annihilate to be constant."""
        k = len(self.names)
        return [[self.A[j][i] - (Fraction(1) if i == j else Fraction(0))
                 for j in range(k)] for i in range(k)]

    def transposed_shift(self, vec):
        """`c . (A x + b)` as coefficients over `x`, plus `c . b`.

        This is the operation the two obligations are stated in: the premise of
        the one-step theorem is that the body's equations hold, and the
        conclusion is what this function computes from them. Written out once so
        the step obligation and the report's display of the candidate are the
        same arithmetic.
        """
        k = len(self.names)
        coef = [Fraction(0)] * k
        for i in range(k):
            if not vec[i]:
                continue
            for j in range(k):
                coef[j] += vec[i] * self.A[i][j]
        return coef, self.dot(vec)

    def lin_text(self, form):
        return show_form(form, self.names)

    def value(self, form, env):
        """An affine form's value, `None` when it names something unknown."""
        total = form[1]
        for nm, v in form[0].items():
            if nm not in env:
                return None
            total += v * env[nm]
        return total


class Candidate:
    """One synthesised affine form, with everything a reader needs to check it.

    `coeffs` are integers over `rel.names`; `const` is an affine form over the
    same names, which is where the DIFFERENCE between an invariant and a
    variant lives: an invariant's constant is `c . x_init` (the value on entry,
    computed), a variant's is derived from the GUARD's bound (the offset that
    makes the form the guard's slack). Both are affine rather than homogeneous
    because a variant's constant is free — `(cA - c) . x + c . b` does not
    mention it — and refusing to derive it would refuse exactly the form a
    reader writes, `bound - counter`.
    """

    __slots__ = ("rel", "coeffs", "const", "role", "text", "why")

    def __init__(self, rel, coeffs, const, role, why=""):
        self.rel = rel
        self.coeffs = dict(coeffs)
        self.const = const
        self.role = role
        self.why = why
        lhs = show_form(({n: Fraction(v) for n, v in coeffs.items()},
                         Fraction(0)), rel.names)
        self.text = (f"{lhs} = {show_form(const, rel.names)}" if role == "invariant"
                     else show_form(self.form(), rel.names))

    @property
    def drop(self):
        """`c . b`: what one iteration does to this form's value."""
        return self.rel.dot([Fraction(self.coeffs.get(n, 0))
                             for n in self.rel.names])

    def form(self):
        """The whole thing as one affine form over `rel.names`."""
        return _af_add(({n: Fraction(v) for n, v in self.coeffs.items()},
                        Fraction(0)), self.const)

    def __repr__(self):
        return f"Candidate({self.role}, {self.text!r}, drop={self.drop})"


def _nullspace_invariant(rel):
    """`{c : cA = c, c . b = 0}`, as compact integer vectors.

    The null space of `[Aᵀ − I ; bᵀ]`, which is exactly that set: a linear
    functional an iteration cannot move. Gauss-Jordan over `Fraction`, so a
    vector with rational components is found exactly rather than rounded into a
    form that is not one.
    """
    k = len(rel.names)
    seen, out = set(), []
    for vec in nullspace(rel.at_i() + [rel.b], k):
        ints = primitive(flip(vec))
        if ints is None or not any(ints):
            continue
        key = tuple(ints)
        if key in seen:
            continue
        seen.add(key)
        out.append(ints)
    return out


def _nullspace_variant(rel):
    """`{c : cA = c, c . b < 0}`, as compact integer vectors.

    The restriction cannot be a filter over a BASIS, and getting that wrong is a
    quiet failure worth naming. `while_lt_acc`'s basis over `(n, i, total)` is
    `{n}` and `{i − total}`, whose drops are 0 and −1, while the variant a
    reader writes is `n − i`, a difference of the two; a filter over the basis
    finds `i − total`, whose non-negativity nothing establishes. So the whole
    space is searched: for each basis vector both signs are tried (the image of
    a linear space under `c ↦ c . b` is a linear subspace of `Q`, and any
    non-zero one is all of `Q`), and every vector with a negative drop is kept.

    A variant's SIGN is therefore never normalised away — unlike an invariant's,
    where `c` and `−c` are the same claim and only one reads well. Flipping a
    candidate here would silently turn the one decreasing functional into the
    one increasing, and the `nonneg` obligation would then fail for a reason
    about the sign rather than about the loop.
    """
    k = len(rel.names)
    seen, out = set(), []
    for base in nullspace(rel.at_i(), k):
        for sign in (1, -1):
            vec = [sign * x for x in base]
            if rel.dot(vec) >= 0:
                continue
            ints = primitive(vec)
            if ints is None:
                continue
            key = tuple(ints)
            if key in seen:
                continue
            seen.add(key)
            out.append(ints)
    return out


def _guard_slack(rel, coeffs):
    """The offset that makes a variant the GUARD's slack, or 0.

    A guard `x_t ⋈ B` says the loop keeps going while `x_t` is below `B`, so the
    form `B - x_t` is the distance to the exit and is the variant a reader
    writes. The algebra alone cannot produce the `B` half — it is a CONSTANT,
    and a constant is invisible to `cA = c` — so it is read off the guard, and
    only when the candidate's coefficient on the guard's own operand is
    non-zero. `for i in range(1, 6)` therefore yields `6 - i` and not `-i`,
    and the difference is the whole of the `nonneg` obligation: `6 - i >= 0`
    follows from the guard, `-i >= 0` follows from nothing.
    """
    guard = rel.shape.guard
    if guard is None or type(guard).__name__ != "BinaryOp":
        return ({}, Fraction(0)), None
    op = getattr(guard, "op", None)
    if op not in ("<", "<=", ">", ">="):
        # `i != 3` is NOT `i < 3` with an offset, and treating it as one is how
        # `arr_fill.mojo` came to be handed `4 - i` as its variant: a decreasing
        # functional, whose non-negativity nothing about `!=` implies.  With no
        # offset the candidate is the bare `-i`, and its `nonneg` obligation is
        # then the honest report that `while i != 4` does not bound `i` above.
        return ({}, Fraction(0)), None
    left, right = guard.left, guard.right
    for probe, bound in ((left, right), (right, left)):
        if type(probe).__name__ != "IdentExpr":
            continue
        if probe.name not in rel.index:
            continue
        c = Fraction(coeffs.get(probe.name, 0))
        if not c:
            continue
        form, why = affine_form(bound, set(rel.names))
        if why:
            return ({}, Fraction(0)), why
        # The offset is `B - probe` MINUS the part of `B` the candidate already
        # carries.  Both halves are needed and the arithmetic is exact:
        # `count_acc`'s guard is `i < n` and its candidate is already `n - i`,
        # so adding a fresh `+ n` would make the variant `2 * n - i`, whose
        # non-negativity nothing establishes; `min_scan`'s guard is `i < 6` and
        # its candidate is `- i`, so the whole `6` is the offset.
        carried = ({}, Fraction(0))
        for nm, v in form[0].items():
            carried = _af_add(carried,
                              ({nm: Fraction(coeffs.get(nm, 0)) * v},
                               Fraction(0)))
        return _af_add(_af_scale(form, -c), _af_scale(carried, Fraction(-1))), None
    return ({}, Fraction(0)), None


#: How many candidates of each role a loop may have emitted. Every candidate is
#: a separate Lean theorem, and a loop whose null space has dimension 20 would
#: otherwise emit 20 theorems to prove something one of them already says. The
#: cap is a DETAIL of the report — which candidates were passed over is printed
#: — rather than a silent truncation, for the reason `MAX_COEFF` is a published
#: number: a search that drops what it found and says nothing about the drop is
#: the `expect=` marker this project keeps arguing with.
MAX_CANDIDATES = 3


def invariant_candidates(rel):
    """The non-trivial affine invariants of `rel`, most compact first.

    A candidate supported only on variables the loop never assigns states that
    those variables keep their value — true, and vacuous as an invariant, since
    `cA = c, c . b = 0` IS "they do not change" and the step theorem then says
    `x' = x → x' = x`. Those are dropped, and their absence is not an invariant
    to report.
    """
    out = []
    for ints in _nullspace_invariant(rel):
        support = {rel.names[i] for i, v in enumerate(ints) if v}
        if not support & set(rel.changes):
            continue
        coeffs = {rel.names[i]: ints[i] for i in range(len(ints)) if ints[i]}
        rhs, why = linear_in_init(rel, coeffs)
        if rhs is None:
            out.append(Candidate(rel, coeffs, ({}, Fraction(0)), "invariant",
                                 why=why))
            continue
        out.append(Candidate(rel, coeffs, rhs, "invariant"))
    out.sort(key=lambda c: (len(c.coeffs), sorted(c.coeffs.items()),
                            c.text))
    return out


def variant_candidates(rel):
    """Every strictly decreasing affine functional of `rel`, most compact first.

    The ordering is the one that decides which of them gets tried first in a
    report, and it is NOT "smallest coefficients": `6 - i` and `-i` have the
    same support, and only the first has a non-negativity the guard implies.
    A candidate whose guard offset was found sorts before one without, because
    that is the difference between a variant whose `nonneg` obligation can close
    and one that cannot.
    """
    out = []
    for ints in _nullspace_variant(rel):
        coeffs = {rel.names[i]: ints[i] for i in range(len(ints)) if ints[i]}
        const, why = _guard_slack(rel, coeffs)
        out.append(Candidate(rel, coeffs, const or ({}, Fraction(0)),
                             "variant", why=why or ""))
    out.sort(key=lambda c: (not c.const[0], len(c.coeffs),
                            sorted(c.coeffs.items()), c.text))
    return out


def linear_in_init(rel, coeffs, free=None):
    """`c . x_init` as an affine form over the function's PARAMETERS.

    The parameters and the pre-loop literals are substituted; anything else in
    an entry value (`best = a[0]`, `i = n + 1`) returns None with the store that
    blocks it. This is where the loop's SYNTHESISED PRECONDITION comes from:
    the hypothesis the variant's non-negativity needs on entry, derived rather
    than written down, and printed whether or not the ladder closes on it.

    `free` is the set of names a substituted entry expression may mention. It
    defaults to the loop's whole scope; a caller narrowing it is saying "this
    candidate may only use the function's parameters", which is what the
    precondition wants and what keeps a pre-loop local from becoming a second
    free variable of the theorem.
    """
    known = set(rel.names) if free is None else set(free)
    total = ({}, Fraction(0))
    for nm in rel.names:
        c = Fraction(coeffs.get(nm, 0))
        if not c:
            continue
        node = rel.shape.init.get(nm, nm)
        if isinstance(node, str):
            if node not in known:
                return None, (f"the entry value of `{nm}` is the parameter "
                              f"`{node}`, and `{node}` is not in the loop's "
                              f"scope")
            form = ({node: Fraction(1)}, Fraction(0))
        else:
            form, why = affine_form(node, known)
            if why:
                return None, f"the entry value of `{nm}`: {why}"
        total = _af_add(total, _af_scale(form, c))
    return total, None


def parameters_of(fn):
    """The function's parameter names, in order."""
    return [p[0] for p in (getattr(fn, "params", None) or [])]


# ── the ladder ───────────────────────────────────────────────────────────────

def ladder_script():
    """`first | omega | simp_all | decide`, built from `LADDER` and re-ordered.

    The rungs are `formal/contracts.py::LADDER`'s and nothing else, read
    through `contracts._ladder_script` so a rung added there is a rung here.
    `test_formal_loop_invariants.py` pins that the SETS are equal, because a
    second hand-written tactic list is the failure `formal/contracts.py`'s own
    comment records having already been committed once inside the module that
    exists to prevent it.

    **`omega` first, and that order is measured.** Every goal here is linear
    integer arithmetic, so `omega` is complete for the ones that are true and
    *refutes* the ones that are not — which is what keeps a wrong candidate
    wrong. `simp_all` first is the order `LADDER` records for
    `formal/contracts.py`'s own goals, and it does not work here: on the
    one-step obligation `c - i = 0 → c' - i' = 0` under `c' = c + 1` and
    `i' = i + 1`, `simp_all` NORMALISES `c' - i'` to `c - i`, reports success
    for the simplification without closing the goal, `first` never reaches
    `omega`, and Lean reports `unsolved goals` on a theorem that is true
    (measured: `.tmp` transcripts behind the module's own first commit; with
    `omega` first the same theorem closes in 0.5 s).
    """
    rungs = [r for r in CT.LADDER if r != "simp_all"] + \
            [r for r in CT.LADDER if r == "simp_all"]
    return "first\n" + "\n".join(f"    | {r}" for r in rungs)


def precondition_text(rel, cand):
    """The hypothesis this candidate needs on entry, as a sentence and a form.

    `c . x_init ≥ 0` for a variant, `c . x_init` itself for an invariant (which
    is what the invariant's own right-hand side says). Returned as
    `(text, form, why)`, with `why` set when the entry values are not linear
    forms — the store that blocks them named, never a zero standing in for it.
    """
    form, why = linear_in_init(rel, cand.coeffs)
    if form is None:
        return None, None, why
    if cand.role == "invariant":
        return "", form, None
    entry = _offset(form, cand.const)
    return f"0 ≤ {show_form(entry, rel.names)}", entry, None


def _int_of(node, rel, what):
    """An expression as Lean `Int`, over the relation's variables, or None."""
    form, why = affine_form(node, set(rel.names))
    if why:
        return None, why
    return show_form(form, rel.names), None


def _cmp_le(left, right):
    """`Int` `<=`, spelled the one way, so no obligation spells it twice."""
    return f"{left} ≤ {right}"


def _offset(form, const):
    """`form + const`: a candidate's two halves as one form."""
    return _af_add(form, const)


def _cmp_pos(node, rel):
    """The guard AS IT HOLDS, as Lean over `Int`.

    The mirror of `_cmp_neg`, and the reason it is a separate function is a
    measured sign error rather than a style preference: `var-nonneg` is the
    obligation that the guard KEEPS the variant non-negative, so it needs the
    guard holding, and the first version of this layer used `_cmp_neg` there
    and asked Lean to prove `0 ≤ n - i` together with `n ≤ i` implies
    `0 ≤ n - i - 1` — which is FALSE, and which omega refuted on all twelve
    shapes, which read exactly like twelve unprovable loops.
    """
    if node is None or type(node).__name__ != "BinaryOp":
        return None, "the loop's guard is not a comparison"
    op = getattr(node, "op", None)
    if op not in CT._COMPARISONS:
        return None, f"the comparison `{op}`"
    left, wl = _int_of(node.left, rel, "guard")
    right, wr = _int_of(node.right, rel, "guard")
    if wl or wr:
        return None, wl or wr
    return f"{left} {op} {right}", None


def _cmp_neg(node, rel):
    """`¬ (the guard)`, as Lean over `Int`.

    The negation of a comparison is computed by the reader and not written out
    as `not (a < b)`, because the difference between `¬(a < b)` and `b ≤ a` is
    one the ladder sees and a reader does not, and only the second is a
    statement `omega` can use directly.
    """
    if node is None or type(node).__name__ != "BinaryOp":
        return None, "the loop's guard is not a comparison"
    op = getattr(node, "op", None)
    flip = {"<": "≥", "<=": ">", ">": "≤", ">=": "<", "==": "≠",
            "!=": "="}.get(op)
    if flip is None:
        return None, f"the comparison `{op}`"
    left, wl = _int_of(node.left, rel, "guard")
    right, wr = _int_of(node.right, rel, "guard")
    if wl or wr:
        return None, wl or wr
    return f"{left} {flip} {right}", None


class Obligation:
    """One thing to prove about one loop, and everything a reader needs.

    `binders` are the `Int` variables it quantifies over; `hyps` are the
    antecedents as an ORDERED list of `(name, proposition)`, so `statement` is
    `hyps[0].p → hyps[1].p → … → conclusion` and the emitted proof `intro`s one
    per arrow.  Order is load-bearing and is why they are one list rather than a
    conjunction with a separate list of names: Lean's `intro` is positional, so a
    conjunction plus a list of names is two lists that have to agree, and this
    is the module's whole subject.  (Measured: the first emitted version
    conjoined the body's equations and still `intro`ed one name per equation,
    and Lean answered `Tactic introN failed: There are no additional binders` on
    every obligation with two equations.)

    `depends` names the other obligations this one's conclusion assumes, which
    is what makes the post's dependence on the variant's non-negativity a
    recorded dependency rather than a reader having to notice it.

    `role` is `inv-init`, `inv-step`, `var-init`, `var-drop`, `var-nonneg`,
    `var-post` or `no-candidate`; `candidate` is the synthesised form this
    obligation is about, or None for the loop-level rows.
    """

    __slots__ = ("name", "role", "conclusion", "binders", "hyps", "depends",
                 "why", "candidate", "theorem", "line", "status", "detail",
                 "witness")

    def __init__(self, name, role, binders, hyps, conclusion, depends, why,
                 candidate=None):
        self.name = name
        self.role = role
        self.binders = list(binders)
        self.hyps = list(hyps)
        self.conclusion = conclusion
        self.depends = list(depends)
        self.why = why
        self.candidate = candidate
        self.theorem = ""
        self.line = 0
        self.status = None
        self.detail = ""
        self.witness = None

    @property
    def refusal(self):
        """Whether this row says the obligation CANNOT BE STATED.

        **Derived from the conclusion, not passed in**, and that is the whole
        design: a flag at six call sites is a flag that can be forgotten at the
        seventh, and the failure it protects against is a green light on
        nothing.  Every real obligation concludes a specific proposition, so the
        placeholder `True` means "no proposition", and the one caller that
        wants a vacuous theorem is a caller whose `why` says it cannot state the
        obligation.

        `sum_acc` is the measured case: its "no affine invariant was derived, so
        the exit value is not determined" row closed over `True` in the first
        version of this layer and reported the loop PROVED — the exact shape
        this module was written to stop.
        """
        return self.conclusion == "True"

    @property
    def statement(self):
        """The whole proposition, as Lean spells it."""
        return " → ".join([p for _n, p in self.hyps] + [self.conclusion])

    def lean(self, ladder=None):
        """The emitted `theorem`, with a docstring saying what it is.

        **A `refusal` row emits a COMMENT and no theorem.**  Its whole content
        is that this layer cannot state the obligation, and a row that says so
        and is then discharged over the placeholder `True` is a green light on
        nothing: `sum_acc`'s "no affine invariant was derived, so the exit value
        is not determined" closed over `True` in the first version of this layer
        and reported the loop PROVED, which is the exact shape this module was
        written to stop.  A refusal is UNKNOWN forever and there is no Lean
        verdict that can move it.
        """
        rungs = ladder or ladder_script()
        if self.refusal:
            # A `--` comment and NOT a `/-- ... -/` docstring: Lean requires a
            # doc comment to be followed by a declaration, and a refusal row
            # declares nothing, so the first version of this emitted a doc
            # comment and Lean answered `unexpected end of input; expected ...
            # 'theorem'` at the end of the file -- which reads as a corrupt
            # proof rather than as a row that deliberately has none.
            head = [f"-- REFUSAL, NOT A ROW THAT CAN PASS: {self.why}",
                    f"-- no theorem is emitted for `{self.name}`; this is "
                    f"UNKNOWN by construction and no Lean verdict can move it.",
                    f"-- What it would have stated: `{self.conclusion}`",
                    "", ""]
            return "\n".join(head)
        body = [f"theorem {self.name} "
                f"{' '.join(f'({b} : Int)' for b in self.binders)} :",
                f"    {self.statement} := by"]
        for h, _p in self.hyps:
            body.append(f"  intro {h}")
        body.append("  " + rungs.replace("\n", "\n  "))
        self.theorem = "\n".join(body) + "\n"
        doc = [f"/-- {self.why}", "",
               "    Given: " + ("; ".join(f"`{p}`" for _n, p in self.hyps)
                              or "nothing") + ".",
               "    Proves: " + f"`{self.conclusion}`.",
               (f"    Uses: {', '.join('`' + d + '`' for d in self.depends)}."
                if self.depends else ""),
               "",
               "    Discharged with `formal/contracts.py::LADDER`, `omega` "
               "first — see `formal/loop_invariants.py::ladder_script` for the "
               "measured reason the order differs from the one "
               "`formal/contracts.py` uses for contracts.",
               "",
               "    Stated over `Int`, where an `Int` is the SIGNED reading of "
               "the program's word (`formal/contracts.py::_signed`, "
               "`lib/ProofLib.lean`'s `sKey`).  It is a claim about the loop's "
               "own arithmetic, not about the machine; "
               "`test_formal_loop_invariants.py` measures the Int model against "
               "CPython and against both images.",
               "-/"]
        return "\n".join(doc + body) + "\n"


# ── rendering one loop's obligations ─────────────────────────────────────────

def _primed(rel):
    """The `rename` for the state AFTER one iteration."""
    return {nm: f"{nm}_1" for nm in _changed(rel)}


def _changed(rel):
    return [n for n in rel.names if n in rel.changes]


def _lhs_form(cand):
    """A candidate's linear part, as a form over the relation's names."""
    return ({n: Fraction(v) for n, v in cand.coeffs.items()}, Fraction(0))


def _lhs_text(cand, rel, primed=False):
    return show_form(_lhs_form(cand), rel.names, _primed(rel) if primed else None)


def _step_hyps(rel):
    """One hypothesis per variable the body changes: `x_1 = <its update>`."""
    return [(f"h_{nm}_1",
             f"{nm}_1 = {show_form(rel.shape.updates[nm], rel.names)}")
            for nm in _changed(rel)]


def _binders(rel):
    return list(rel.names) + [f"{nm}_1" for nm in _changed(rel)]


def build_obligations(shape, rel, source="<source>"):
    """The obligations for one loop, plus the candidates they are about.

    Returns `(obligations, invariants, variants, every, every_var)`.  The order
    is the one a reader wants: each candidate's initiation and one-step
    preservation first, then its initiation, drop and preservation of
    non-negativity, then the exit consequence.

    **A loop with no candidate still gets an obligation**, whose role is
    `no-candidate` and whose `why` names the store that blocked the search.  A
    caller reading only the statuses cannot then tell "proved" from "never
    looked", which is the distinction this project keeps paying for.
    """
    fn_name = getattr(shape.fn, "name", None) or "<fn>"
    prefix = f"{fn_name}_loop{shape.index}"
    every_inv = invariant_candidates(rel)
    every_var = variant_candidates(rel)
    out = []
    if not every_inv and not every_var:
        out.append(Obligation(
            f"{prefix}_no_candidate", "no-candidate", [], [],
            "True", [],
            why=("this loop has no affine transition to be an invariant over, "
                 "so NO candidate was derived and the obligation says that "
                 "rather than nothing: " + _no_candidate_reason(shape, rel))))
        return out, [], [], [], [], None

    # **ONE candidate of each role carries the obligations.**  The rest are
    # REPORTED (the header's list and the ledger) rather than discharged, for two
    # reasons that pull the same way: every candidate is a separate Lean
    # theorem, so a loop whose null space has dimension 20 would emit 20 of them
    # to prove something one of them already says; and a roll-up over ALL of
    # them could never be PROVED, because some member of any large enough family
    # is a variant whose non-negativity nothing implies.  The header names every
    # candidate, so nothing is hidden by the choice.
    invs = every_inv[:1]
    variant_used = every_var[:1]
    if invs:
        out.extend(_invariant_obligations(shape, rel, invs[0], 1, prefix))
    precondition = None
    if variant_used:
        out.extend(_variant_obligations(shape, rel, variant_used[0], 1, prefix))
        precondition = precondition_text(rel, variant_used[0])[0]
    out.extend(_post_obligations(shape, rel, invs, variant_used, prefix))
    return out, invs, variant_used, every_inv, every_var, precondition


def _no_candidate_reason(shape, rel):
    """Why nothing was derived, naming the store rather than the shape."""
    if shape.blocked:
        first = sorted(shape.blocked)[0]
        return (f"the body assigns `{first}` a value that is not a linear form "
                f"({shape.blocked[first]}), and a candidate may only mention a "
                f"variable the body assigns linearly in EVERY branch — which "
                f"leaves the loop's scalar variables as "
                f"{', '.join(rel.names) or 'none'} with nothing decreasing "
                f"among them")
    return (f"the loop's variables ({', '.join(rel.names) or 'none'}) admit no "
            f"linear functional the transition leaves constant and no linear "
            f"functional it strictly drops")


def _invariant_obligations(shape, rel, cand, k, prefix):
    """`inv-init` and `inv-step` for one candidate."""
    out = []
    names = rel.names
    lhs = _lhs_text(cand, rel)
    rhs = show_form(cand.const, names)
    claim = f"{lhs} = {rhs}"
    entry_hyps, entry_why = [], None
    for nm in names:
        if not cand.coeffs.get(nm):
            continue
        node = shape.init.get(nm, nm)
        entry, why = _int_of(node, rel, nm)
        if why:
            entry_why = why
            break
        if not (isinstance(node, str) and node not in rel.index):
            entry_hyps.append((f"h0_{nm}", f"{nm} = {entry}"))
    if entry_why:
        out.append(Obligation(
            f"{prefix}_inv{k}_init", "inv-init", names, [], claim, [],
            candidate=cand,
            why=(f"the invariant `{claim}` CANNOT be stated on entry: the "
                 f"entry value is not a linear form — {entry_why}.  Reported "
                 f"as UNKNOWN rather than omitted, because an invariant that "
                 f"cannot be stated where the loop starts is a gap and not a "
                 f"pass.")))
    else:
        out.append(Obligation(
            f"{prefix}_inv{k}_init", "inv-init", names, entry_hyps, claim, [],
            candidate=cand,
            why=(f"the invariant `{claim}` holds on entry.  Its right-hand side "
                 f"is `c . x_init`, COMPUTED from the loop's own entry values, "
                 f"and the hypotheses are that loop's own pre-loop stores — so "
                 f"this obligation says the computation agrees with the "
                 f"program"
                 + (f"." if entry_hyps else
                    ", and there are no pre-loop stores to disagree with it, so "
                    "the obligation has no hypotheses."))))
    step = _step_hyps(rel)
    primed = _lhs_text(cand, rel, primed=True)
    out.append(Obligation(
        f"{prefix}_inv{k}_step", "inv-step", _binders(rel),
        step + [(f"hinv{k}", claim)], primed + f" = {rhs}",
        [f"{prefix}_inv{k}_init"], candidate=cand,
        why=(f"one iteration of this loop preserves `{claim}`.  The given "
             f"equations are the body's OWN, so the conclusion is what the "
             f"source's arithmetic gives rather than a restatement of it — and "
             f"a candidate that is NOT an eigen-invariant is REFUTED by this "
             f"same obligation, which is what makes the negative control in the "
             f"test file mean something.")))
    return out


def _variant_obligations(shape, rel, cand, k, prefix):
    """`var-init`, `var-drop` and `var-nonneg` for one candidate."""
    out = []
    names = rel.names
    form = show_form(cand.form(), names)
    drop = abs(cand.drop)
    step = _step_hyps(rel)
    if not step:
        return out
    pre_text, _pre_form, _pre_why = precondition_text(rel, cand)
    entry_form, entry_why = linear_in_init(rel, cand.coeffs)
    entry_text = (show_form(_offset(entry_form, cand.const), names)
                  if entry_form is not None else None)
    blocked = entry_why

    # **NO `var-init` AND NO `var-pre` OBLIGATION, and their absence is the
    # point.**  `0 <= c . x_init` is the loop's SYNTHESISED PRECONDITION, not a
    # theorem about the program: `count_acc`'s is `0 <= n`, which the program
    # does not establish for an arbitrary `n` and could not — `count_acc(-1)` is
    # 0, not -1.  Emitting it as an obligation made Lean refute it on every
    # shape, and the `simp_all made no progress` that followed read like a
    # defect in the emitter rather than like a premise being mistaken for a
    # claim.  It is carried on the verdict as `precondition`, printed in the
    # emitted file's header, in the report and in the ledger, and every other
    # row is read under it.
    precondition = pre_text

    primed = show_form(cand.form(), names, _primed(rel))
    minus = f"{form} - {drop}" if drop != 1 else f"{form} - 1"
    out.append(Obligation(
        f"{prefix}_var{k}_drop", "var-drop", _binders(rel), step,
        f"{primed} = {minus}", [], candidate=cand,
        why=(f"one iteration of this loop drops `{form}` by exactly {drop}, "
             f"which is what makes the loop terminate.  The guard is "
             f"deliberately NOT given: the drop follows from the body's "
             f"equations alone and holds in EVERY state, which is the stronger "
             f"statement and the one `omega` can use.")))
    guard_holds, guard_why = _cmp_pos(shape.guard, rel)
    if guard_why:
        out.append(Obligation(
            f"{prefix}_var{k}_nonneg", "var-nonneg", names, [], "True", [],
            candidate=cand,
            why=(f"the variant's non-negativity cannot be stated under the "
                 f"guard, because {guard_why}.  UNKNOWN with that reason.")))
    else:
        out.append(Obligation(
            f"{prefix}_var{k}_nonneg", "var-nonneg", _binders(rel),
            step + [(f"hvar{k}", f"0 ≤ {form}"),
                    (f"hgt{k}", f"({guard_holds})")],
            f"0 ≤ {primed}", [], candidate=cand,
            why=(f"the guard `{_show_node(shape.guard)}` keeps `{form}` "
                 f"non-negative, so the variant cannot pass through a state "
                 f"where it is not a bound.  This is the obligation that says "
                 f"`while i != k` does NOT bound `i` above, when that is what "
                 f"the loop wrote — `arr_fill.mojo` is that program, and its "
                 f"verdict here is the point of having the obligation.")))
    return out


def _answer_forms(rel, shape):
    """The candidate ANSWERS an exit postcondition may name, most likely first.

    The function's parameters, then whatever the guard compares against, then
    `0` and `1`.  Parameters first because a loop's answer is nearly always a
    function of one, and the guard's operand because a loop over a literal
    bound is answered by that bound.
    """
    out, seen = [], set()

    def offer(form):
        text = show_form(form, rel.names)
        if text in seen:
            return
        seen.add(text)
        out.append(form)

    for p in parameters_of(shape.fn):
        if p in rel.index:
            offer(({p: Fraction(1)}, Fraction(0)))
    if shape.guard is not None and type(shape.guard).__name__ == "BinaryOp":
        for side in (shape.guard.left, shape.guard.right):
            form, why = affine_form(side, set(rel.names))
            if not why:
                offer(form)
    offer(({}, Fraction(0)))
    offer(({}, Fraction(1)))
    return out


def _post_obligations(shape, rel, invs, variants, prefix):
    """The exit consequence: what the loop's value is when the guard fails.

    **ONE emitted postcondition, for the top answer candidate that the
    invariants do not already imply**, and the other candidates are NAMED in its
    `why` rather than emitted.  A loop's answer is one of several CANDIDATE
    answers — `c = n`, `c = i`, `c = 0` are three guesses at the same thing —
    and the first is the one a reader wants.  Emitting all of them put
    deliberately-false theorems in the generated file, which made `lean` exit
    non-zero on a loop whose real postcondition closed, and that is exactly the
    signal a build reads as "this proof is broken".  The rejections belong in
    `test_formal_loop_invariants.py`, where they are negative controls with
    names; here they are a sentence.
    """
    out = []
    ret, why_ret = _int_of(shape.post, rel, "the return")
    if why_ret:
        return [Obligation(
            f"{prefix}_post", "var-post", names_of(rel), [], "True", [],
            why=(f"no postcondition can be stated: the loop's return value is "
                 f"`{_show_node(shape.post)}` and {why_ret}.  The candidates "
                 f"above are unaffected; the VALUE is what this row is "
                 f"about."))]
    if not invs:
        return [Obligation(
            f"{prefix}_post", "var-post", names_of(rel), [], "True", [],
            why=("no postcondition is stated because NO affine invariant was "
                 "derived, so the exit state is not determined: a variant says "
                 "how far the loop MAY run, and nothing here says what its "
                 "value is when it stops.  That is an honest UNKNOWN and not a "
                 "gap in the report — an accumulator stepped by the counter has "
                 "a closed form this layer's LINEAR arithmetic cannot state."))]
    if not variants:
        return [Obligation(
            f"{prefix}_post", "var-post", names_of(rel), [], "True", [],
            why=("no postcondition is stated because no VARIANT was derived, "
                 "so nothing bounds the loop's counter from the outside and the "
                 "invariant alone does not determine the exit state."))]
    guard_neg, guard_why = _cmp_neg(shape.guard, rel)
    if guard_why:
        return [Obligation(
            f"{prefix}_post", "var-post", names_of(rel), [], "True", [],
            why=f"no postcondition is stated: {guard_why}")]
    inv = invs[0]
    var = variants[0]
    lhs = _lhs_text(inv, rel)
    rhs = show_form(inv.const, rel.names)
    form = show_form(var.form(), rel.names)
    ret_form, _rw = affine_form(shape.post, set(rel.names))
    tried, chosen = [], None
    for ans in _answer_forms(rel, shape):
        ans_text = show_form(ans, rel.names)
        if _implied_by_invariants(ret_form, ans, invs):
            tried.append(f"`{ret} = {ans_text}` (already the invariant)")
            continue
        if chosen is None:
            chosen = (ans, ans_text)
            tried.append(f"`{ret} = {ans_text}` (TRIED)")
        else:
            tried.append(f"`{ret} = {ans_text}` (not tried)")
    if chosen is not None:
        ans, ans_text = chosen
        out.append(Obligation(
            f"{prefix}_inv1_post", "var-post", names_of(rel),
            [(f"hinv", f"{lhs} = {rhs}"), (f"hguard", f"({guard_neg})"),
             (f"hvar", f"0 ≤ {form}")],
            f"{ret} = {ans_text}",
            [f"{prefix}_inv1_step", f"{prefix}_var1_nonneg"], candidate=inv,
            why=(f"when the loop stops, its return value `{ret}` is "
                 f"`{ans_text}`.  The three givens are the invariant, the "
                 f"negation of the guard, and the variant's non-negativity "
                 f"`0 ≤ {form}` — the third is what says the counter cannot "
                 f"have gone PAST the bound, and without it the same two admit "
                 f"a state where the loop has run on, which is the difference "
                 f"between a derivation and a guess."
                 + ("  Answer candidates: " + "; ".join(tried) + "."
                    if tried else ""))))
    return out


def names_of(rel):
    return list(rel.names)


def _implied_by_invariants(ret, answer, invs):
    """Whether an invariant ALREADY says the return value is this answer.

    `c = i` under the invariant `c - i = 0` is the invariant, not a new claim,
    and a report that listed it as the loop's postcondition would be reporting
    the loop's own input back as its output.  The test is exact: `ret - answer`
    must be a rational MULTIPLE of one synthesised invariant's direction, over a
    small range of multiples because the vectors are small integers by
    construction (`MAX_COEFF`) and a genuine multiple cannot exceed the cap.
    """
    if ret is None:
        return False
    target = _af_add(ret, _af_scale(answer, Fraction(-1)))
    if target[1] or not target[0]:
        return False
    for cand in invs:
        span = ({n: Fraction(v) for n, v in cand.coeffs.items()}, Fraction(0))
        for k in range(-MAX_COEFF, MAX_COEFF + 1):
            if k and _af_scale(span, Fraction(k)) == target:
                return True
    return False


# ── the file, and reading the verdicts back out of it ────────────────────────

def self_reason(ob):
    """The reason a refusal row carries, repeated so the verdict is not blank."""
    return ("this layer cannot state this obligation, and the row says why: "
            + ob.why.split(".  ")[0])


def proof_text(obligations, header=""):
    """One `.lean` file for a whole set of obligations, plus the line index.

    Returns `(text, {obligation name: 1-based line of its `theorem`})`.  The
    index is what makes ONE Lean run answer N questions: Lean reports
    `file:LINE:COL: error: …`, and the line is all that is needed to say which
    obligation it is about.  Running Lean per obligation instead would be N
    elaborations of the same imports for an answer this already gives.

    **The file imports NOTHING.**  Every obligation is linear integer arithmetic
    over `Int`, which needs no `lib/*.olean`, so this whole layer costs one
    `lean` invocation of a few hundred lines and no library build — measured at
    0.3 s wall, 0.0 s CPU, 0.02 GB on `count_acc`.  That is also why the
    obligations are stated over `Int` rather than `UInt64`; the module
    docstring has the argument and `test_formal_loop_invariants.py` measures the
    Int model against CPython and against both images.
    """
    lines = [LEAN_PRELUDE.rstrip("\n"), ""]
    if header:
        lines.extend(header.rstrip("\n").split("\n"))
        lines.append("")
    index = {}
    # The index counts LINES, not the elements of `lines`: each element is a
    # whole multi-line obligation, so `len(lines) + 1` is the number of
    # obligations emitted so far and not a line number.  Measured: with the
    # element count, every obligation's span was two lines long and sat over its
    # predecessor's docstring, so `arr_fill`'s `var-nonneg` failure was reported
    # against `var-post` and the loop's own summary counted 2 of 3 closed when
    # Lean had closed 1.
    emitted = len(LEAN_PRELUDE.rstrip("\n").split("\n")) + 1
    for ob in obligations:
        text = ob.lean()
        index[ob.name] = emitted + (len(header.rstrip("\n").split("\n")) + 1
                                    if header else 0)
        emitted += len(text.rstrip("\n").split("\n")) + 1
        lines.append(text.rstrip("\n"))
        lines.append("")
    return "\n".join(lines) + "\n", index


_LEAN_ERROR = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+):(?P<col>\d+): "
                         r"error: (?P<msg>.*)$")


def read_lean_verdicts(text, detail, index, obligations):
    """Per-obligation verdicts out of ONE Lean's output, by line.

    `detail` is Lean's own stdout and `index` the map `proof_text` returned.  An
    obligation is PROVED when no error line falls inside its span and UNKNOWN
    with Lean's own sentence when one does.

    Two consequences worth stating, because they are what make this a verdict
    and not a score:

      * an error BEFORE the first obligation is not any obligation's fault, so
        every obligation is UNKNOWN with that error attached rather than one of
        them being blamed for a file that would not elaborate at all; and
      * `warning:` lines are not errors, so an unused binder does not turn a
        proved theorem into an unproved one — the linter is silenced in the
        prelude for the same reason.

    Returns `(errors inside the obligations, errors before them)`.
    """
    errors = []
    for raw in (detail or "").splitlines():
        m = _LEAN_ERROR.match(raw)
        if m:
            errors.append((int(m.group("line")), m.group("msg")))
    errors.sort()
    n_lines = len((text or "").split("\n")) + 1
    spans = []
    for i, ob in enumerate(obligations):
        start = index.get(ob.name)
        if start is None:
            continue
        end = (index[obligations[i + 1].name] - 1
               if i + 1 < len(obligations) else n_lines)
        spans.append((start, end, ob))
    first_line = min((s for s, _e, _o in spans), default=None)
    global_errors = [f"line {ln}: {msg}" for ln, msg in errors
                     if first_line is not None and ln < first_line]
    inside = 0
    for start, end, ob in spans:
        own = [f"line {ln}: {msg}" for ln, msg in errors if start <= ln < end]
        inside += len(own)
        if ob.refusal:
            # A refusal is UNKNOWN whatever Lean said, and an error inside its
            # comment is a BUG in the emitter rather than a fact about the loop.
            if own:
                ob.detail = ("the emitter wrote an error inside a refusal row, "
                             "which emits no theorem: " + "; ".join(own[:3]))
            else:
                ob.detail = self_reason(ob)
            continue
        if global_errors:
            ob.status = UNKNOWN
            ob.detail = ("the file did not elaborate before this obligation: "
                         + "; ".join(global_errors[:4]))
        elif own:
            ob.status = UNKNOWN
            ob.detail = "; ".join(own[:3])
        else:
            ob.status = PROVED
            ob.detail = f"Lean closed `{ob.name}` with the ladder"
    return inside, len(global_errors)


# ── the bounded search ───────────────────────────────────────────────────────
#
# It reads the loop's OWN statements through `formal/contracts.py`'s one
# expression IR and evaluates them with its one evaluator, in that module's
# `UInt64` word semantics, then reads each word back SIGNED.  So it is a check
# of the SOURCE and not of this module's affine reading — the difference
# matters, because an affine reader that is wrong in the same way twice would
# agree with itself and refute nothing.

def _eval_form(form, env):
    """An affine form's value over a signed-`Fraction` environment."""
    total = form[1]
    for nm, v in form[0].items():
        if nm not in env:
            return None
        total += v * env[nm]
    return total


def _word_env(env):
    """The signed-`Fraction` state as the words `formal/contracts.py` reads.

    The IR evaluator works in `UInt64` word semantics and reads a comparison as a
    SIGNED order, so the search's exact `Fraction` state is handed over as the
    words it denotes.  At the search's bounds (`inputs <= 11`, `steps <= 24`)
    no value leaves a word, which is why the two readings agree; the module
    docstring says which layer the Int model is and
    `test_formal_loop_invariants.py` measures it.
    """
    return {k: int(v) & CT._MASK for k, v in env.items()}


def _guard_compare(guard, names):
    """The loop's guard as ONE proposition in `formal/contracts.py`'s IR.

    Read through that module's IR reader with the loop's OWN variable names —
    which is the reason the reader is asked rather than the affine reader above:
    the guard is evaluated over `UInt64` word semantics by that module's
    evaluator, so the bounded search checks the SOURCE's comparison rather than
    this module's restatement of it.  Two failures this shape had to be taught,
    both of which look like "the search found nothing":

      * a reader with the wrong name set returns None for every operand, and
        that is a search that skips every input (measured: with an empty name
        set every candidate reported `skipped = 12`); and
      * asking the reader for `guard.left` and `guard.right` instead of for the
        guard returns the TRUTHINESS of the two operands, so `i < n` became
        "i is nonzero and n is nonzero" — and the search then walked states the
        program never reaches and missed the ones it does.  The reader's
        `truth` is the whole proposition and is asked once.
    """
    if guard is None:
        return None
    ir = CT._Reader(set(names)).truth(guard)
    return ir


def _guard_holds(guard_ir, env):
    """The loop's guard at this state, or None when it cannot be evaluated."""
    if guard_ir is None:
        return None
    try:
        return bool(CT._eval_of(guard_ir, _word_env(env), [CT.SEARCH_FUEL]))
    except Exception:
        return None


def _arms_of(shape):
    """The body's straight-line ARMS: `[(condition, [statements])]`.

    An `if` in the body doubles the arms, and each arm is its own path — NOT a
    concatenation of them.  Concatenating would apply `v = v // 2` and
    `v = 3 * v + 1` in the same iteration, which is a state no iteration of
    `collatz` is in, and a search that walked such a state could only report on
    a program nobody wrote.
    """
    arms = [(None, list(shape.body))]
    for st in shape.body:
        if type(st).__name__ != "IfStmt":
            continue
        nxt = []
        for _cond, plan in arms:
            for cond, sub in _if_paths_pairs(st):
                nxt.append((cond, plan + list(sub or [])))
        arms = nxt
    return arms


def _if_paths_pairs(st):
    """`[(condition, body)]` for one `if`, with the no-else arm's None."""
    arms = [(st.condition, list(getattr(st, "then_body", None) or []))]
    for cond, sub in (getattr(st, "elifs", None) or []):
        arms.append((cond, list(sub or [])))
    if getattr(st, "else_body", None):
        arms.append((F.BoolLiteral(True, 0, 0), list(st.else_body)))
    else:
        arms.append((None, []))
    return arms


def _one_step(env, arms, shape, rel):
    """One iteration, evaluated from the loop's own statements.

    The arm is CHOSEN by the `if` conditions, each evaluated by
    `formal/contracts.py`'s evaluator over the state; an `if` whose condition
    cannot be evaluated makes the whole step unreadable, and an unreadable step
    is a skip and not a state.
    """
    fuel = [CT.SEARCH_FUEL]
    names = rel.names
    chosen = None
    for cond, plan in arms:
        if cond is None:
            continue
        ir = CT._Reader(set(names) | set(env)).truth(cond)
        if ir is None:
            return None
        try:
            if CT._eval_of(ir, _word_env(env), fuel):
                chosen = plan
                break
        except Exception:
            return None
    # The FLATTENING matters and was the bug: `arms` is a list of
    # `(condition, [statements])`, so `[plan for cond, plan in arms …]` is a
    # list of LISTS and iterating it hands `_one_step` a list where it expects a
    # statement.  Every input was then a skip, and a skip looks exactly like
    # "no counterexample" — which is why the `tilt` control found nothing on
    # `count_acc` while the offset control still fired at iteration 0.
    stmts = (list(chosen) if chosen is not None
             else [s for _cond, plan in arms if _cond is None for s in plan])
    if not stmts:
        return None
    reader = CT._Reader(set(env))
    for st in stmts:
        kind = type(st).__name__
        if kind not in ("AssignStmt", "AugAssignStmt", "VarDecl"):
            return None
        target = st.target if kind != "VarDecl" else F.IdentExpr(st.name)
        if type(target).__name__ != "IdentExpr" or target.name not in env:
            return None
        if kind == "AugAssignStmt":
            op = {"+=": "+", "-=": "-", "*=": "*"}.get(st.op)
            if op is None:
                return None
            value = F.BinaryOp(op, F.IdentExpr(target.name), st.value, 0, 0)
        else:
            value = st.value
        ir = reader.value(value)
        if ir is None:
            return None
        try:
            env[target.name] = Fraction(CT._signed(CT._eval_of(
                ir, _word_env(env), fuel)))
        except Exception:
            return None
    if shape.kind == "for-range":
        env[shape.target] = env.get(shape.target, Fraction(0)) + 1
    return env


def refute(shape, rel, cand, inputs=None, steps=SEARCH_STEPS, perturb=None,
           offset=None, tilt=None):
    """A concrete state at which `cand` fails, or None.

    **What a failure is depends on the role, and both are the textbook one.**
    An invariant is refuted when the form's value differs from its claimed
    right-hand side at some state the loop actually reaches.  A variant is
    refuted when the form is NEGATIVE at some state the loop reaches with its
    guard still true — which is the property that makes it a bound, and the one
    `while i != 4` fails.

    **THE NEGATIVE CONTROLS, and they are the same function.**  Three ways to
    make the candidate wrong, all decided here rather than by a second code
    path, because a control built by different code from the thing it controls
    is a control that proves nothing about it:

      `perturb`  multiply every coefficient.  This is a control only for a
                 candidate whose claimed value is NON-zero — `count_acc`'s is
                 `c - i = 0` and `2c - 2i = 0` is implied by it, so scaling that
                 one is not a wrong claim at all (measured: scale 2 over
                 `count_acc` finds nothing, and a test that read that as "the
                 search cannot refute" would have been measuring the wrong
                 thing).  `dec_measure`'s is `i + 2*s = n`, and scaling it IS
                 refuted at iteration 0.
      `offset`   add a constant to the CLAIMED value.  Refutes any invariant
                 whose right-hand side is computed, at the first state the loop
                 reaches — the control that works for `c - i = 0`.
      `tilt`     add a constant to ONE coefficient, which takes the candidate
                 off the eigenvector set.  This is the control that says the
                 SYNTHESIS is what makes the claim true.

    The states come from the loop's OWN statements, read through
    `formal/contracts.py`'s expression IR and evaluated by its evaluator in that
    module's `UInt64` word semantics, then read back SIGNED.  The candidate's own
    value is computed in exact `Fraction` arithmetic from the affine form, so a
    refutation is about the loop's execution and not about this module's reading
    of it.

    **This is a check, not a proof.**  It explores `inputs x (steps + 1)` states;
    `PROVED` can only come from Lean.  An input the source evaluator cannot run
    is counted in `skipped`, and a skip is NOT agreement.

    Returns `(witness or None, skipped)`.
    """
    names = rel.names
    params = [p[0] for p in (getattr(shape.fn, "params", None) or [])]
    scale = Fraction(perturb) if perturb else Fraction(1)
    coeffs = {n: Fraction(v) * scale for n, v in cand.coeffs.items()}
    if tilt:
        var, by = tilt
        coeffs[var] = coeffs.get(var, Fraction(0)) + Fraction(by)
    # **An INVARIANT and a VARIANT put the constant on opposite sides of the
    # comparison**, and getting that wrong is a false REFUTED in both
    # directions.  An invariant reads `lhs = rhs`, so its offset is the RIGHT
    # HAND SIDE; a variant reads `form >= 0`, so its offset is part of the form.
    # Measured: putting the variant's offset on the left refuted `n - i` (which
    # is `-i` with the offset `+n`, derived from the guard) at `n = 2, i = 1`,
    # and putting the invariant's offset on the left refuted `i + 2*s = n` at
    # its own entry state.
    if cand.role == "invariant":
        lhs = (coeffs, Fraction(0))
        claim_form = _af_add(_af_scale(cand.const, scale),
                             ({}, Fraction(offset) if offset else Fraction(0)))
    else:
        lhs = _af_add((coeffs, Fraction(0)), _af_scale(cand.const, scale))
        claim_form = ({}, Fraction(0))
    guard_ir = _guard_compare(shape.guard, names)
    arms = _arms_of(shape)
    skipped = 0
    for value in (inputs if inputs is not None else SEARCH_INPUTS):
        env = {p: Fraction(value) for p in params}
        bad = False
        reader = CT._Reader(set(names))
        for nm in names:
            entry = shape.init.get(nm, nm)
            if isinstance(entry, str):
                env.setdefault(nm, Fraction(value))
                continue
            ir = reader.value(entry)
            if ir is None:
                bad = True
                break
            # The entry expression is read in the environment the PARAMETERS are
            # already in — `i = n` is `n`, and evaluating it against zeroes makes
            # every loop whose counter starts at a parameter look refuted at
            # iteration 0.  Measured: that bug reported `dec_measure`'s invariant
            # `i + 2*s = n` as REFUTED at n = 1 with `i = 0`.
            try:
                env[nm] = Fraction(CT._signed(CT._eval_of(
                    ir, _word_env(env), [CT.SEARCH_FUEL])))
            except Exception:
                bad = True
                break
        if bad:
            skipped += 1
            continue
        for step in range(steps + 1):
            got = _eval_form(lhs, env)
            if got is None:
                bad = True
                break
            if cand.role == "invariant":
                claim = _eval_form(claim_form, env)
                if claim is None:
                    bad = True
                    break
                if got != claim:
                    return ({"input": value, "iterations": step, "form": got,
                             "claimed": claim,
                             "state": {k: str(v)
                                       for k, v in sorted(env.items())}},
                            skipped)
            elif got < 0 and _guard_holds(guard_ir, env) is True:
                return ({"input": value, "iterations": step, "form": got,
                         "claimed": Fraction(0),
                         "state": {k: str(v) for k, v in sorted(env.items())}},
                        skipped)
            holds = _guard_holds(guard_ir, env)
            if holds is None:
                bad = True
                break
            if holds is False:
                break
            env = _one_step(env, arms, shape, rel)
            if env is None:
                bad = True
                break
        if bad:
            skipped += 1
    return None, skipped


# ── the family vocabulary ────────────────────────────────────────────────────
#
# A LABEL, and nothing is proved by it.  It exists so the report and the
# regression baseline group by the shape the task names — a sum accumulator, a
# product accumulator, a count accumulator, a min/max scan, a linear search, an
# array fill/copy, a decreasing-measure loop, a collatz loop — and so a reader
# can ask "what does this layer do for a MIN SCAN" without reading the file.
# Each rule is a predicate over the READ loop, and each names the rule's own
# text, so a shape that matches two of them says which one it matched and which
# it missed.

def _nodes(stmts):
    """Every node under `stmts`, from `formal/model.py`'s own walker."""
    from formal.model import iter_nodes
    return list(iter_nodes(stmts))


def family_of(shape):
    """`(name, why)` for one loop, from the READ SHAPE ALONE.

    **A LABEL, and nothing is proved by it.**  It exists so the report and the
    regression baseline group by the shape the task names — a sum accumulator, a
    product accumulator, a count accumulator, a min/max scan, a linear search, an
    array fill/copy, a decreasing-measure loop, a collatz loop — and so a reader
    can ask "what does this layer do for a MIN SCAN" without reading the file.
    Each rule is a predicate over the read loop and each returns its own rule's
    text, so a shape that matches two of them says which one it matched and which
    it missed.

    **The predicates are STRUCTURAL, over `iter_nodes`, and never over the
    printed text.**  Two measured reasons, both from the first version:

      * `collatz.mojo`'s `v = v // 2` is inside an `if`, so a test over the
        loop's TOP-LEVEL statements found no `//` and labelled it
        `countdown-while`;
      * `min_scan.mojo` and `max_scan.mojo` were labelled `count-accumulator`
        by a test over the accumulator's step, which `i = i + 1` satisfies, and
        `arr_copy.mojo` was labelled `min-scan` by a test over whether the text
        contained a `<`.  A census that groups by this field is then a census of
        the wrong thing.

    The order is the order of specificity, and the ARRAY test comes FIRST
    because a loop that reads or writes through a subscript is an array loop
    whatever else it does.

      `array-fill` / `array-copy`   the body stores a LITERAL through a
                            subscript / reads one and stores it elsewhere
      `min-scan` / `max-scan`  the body stores a subscripted read into an
                            accumulator under `<` / `>`
      `linear-search`       the body leaves the loop on a subscripted read
      `collatz`             the body HALVES or TRIPLES a variable
      `modulo-loop`         the body takes a `%`
      `count-accumulator`   a for-range loop whose body is one accumulator
                            stepped by 1
      `sum-accumulator`     … stepped by the counter
      `product-accumulator` … stepped by a product
      `decreasing-measure`  a while loop whose test is an ORDER on a variable
                            the body moves away from that bound
      `countdown-while`     a while loop whose test is an EQUALITY
      `counted-while`       anything else this layer read
    """
    nodes = _nodes(shape.body)
    kinds = [type(n).__name__ for n in nodes]
    subs = [n for n in nodes if type(n).__name__ == "SubscriptExpr"]
    cmps = [getattr(n, "op", None) for n in nodes
            if type(n).__name__ == "BinaryOp" and getattr(n, "op", None)
            in ("<", "<=", ">", ">=")]
    leaves = any(t in ("ReturnStmt", "BreakStmt", "ContinueStmt")
                 for t in kinds)
    if subs:
        under_cmp = any(getattr(n, "op", None) in ("<", "<=", ">", ">=")
                        and any(type(x).__name__ == "SubscriptExpr"
                                for x in _nodes(n)) for n in nodes)
        where = (f"(`{_show_node(subs[0].obj)}[{_show_node(subs[0].index)}]`)")
        if leaves and under_cmp:
            return ("linear-search",
                    f"the body leaves the loop on a comparison about a "
                    f"subscripted element {where}")
        if under_cmp:
            op = ">" if ">" in cmps else "<"
            return (f"{'max' if op == '>' else 'min'}-scan",
                    f"the body keeps a running extremum under `{op}` over "
                    f"{where}")
        lits = [n for n in nodes if type(n).__name__ == "AssignStmt"
                and type(n.value).__name__ == "IntLiteral"]
        return (("array-fill" if lits else "array-copy"),
                f"the body stores through a subscript {where}"
                + (f" and writes the literal `{_show_node(lits[0].value)}`"
                   if lits else " and copies one element to another"))
    ops = [getattr(n, "op", None) for n in nodes
           if type(n).__name__ == "BinaryOp"]
    if "//" in ops:
        return ("collatz",
                "the body HALVES a variable (`//`), the collatz shape")
    if "%" in ops:
        return ("modulo-loop",
                "the body takes a `%`, the gcd shape")
    if "*" in ops and any(getattr(getattr(n, "left", None), "value", None) == 3
                          or getattr(getattr(n, "right", None), "value", None)
                          == 3 for n in nodes
                          if type(n).__name__ == "BinaryOp"
                          and getattr(n, "op", None) == "*"):
        return ("collatz",
                "the body TRIPLES a variable and adds one, the collatz shape")
    prod = [n for n in nodes if type(n).__name__ == "BinaryOp"
            and getattr(n, "op", None) == "*"
            and type(n.left).__name__ != "IntLiteral"
            and type(n.right).__name__ != "IntLiteral"]
    if prod:
        return ("product-accumulator",
                f"the body multiplies `{_show_node(prod[0].left)}` by "
                f"`{_show_node(prod[0].right)}`, neither of them a constant")
    assigns = shape.updates
    if shape.kind == "for-range":
        # The TARGET is skipped: `i = i + 1` is the loop's own step and
        # classifies as a count accumulator, which is how `sum_acc.mojo` was
        # labelled `count-accumulator` in the first version of this rule.
        for nm in sorted(n for n in assigns if n != shape.target):
            form = assigns[nm]
            shown = show_form(form, shape.names)
            if set(form[0]) == {nm} and form[1] == 1:
                return ("count-accumulator",
                        f"`{nm} = {shown}` steps the accumulator by 1 per "
                        f"iteration, so the loop counts")
            if set(form[0]) == {nm, shape.target} and form[1] == 0:
                return ("sum-accumulator",
                        f"`{nm} = {shown}` adds the counter to the accumulator")
            return ("accumulator-not-classified",
                    f"`{nm} = {shown}` is an accumulator step this vocabulary "
                    f"does not name; the shape is read and the candidate is "
                    f"synthesised from it either way")
        return ("counted-while",
                f"a for-range loop over {len(assigns)} accumulator(s) this "
                f"layer read")
    guard_op = getattr(shape.guard, "op", None)
    if guard_op in ("<", "<=", ">", ">="):
        return ("decreasing-measure",
                f"a while loop whose test `{_show_node(shape.guard)}` is an "
                f"order on a counter the body moves toward that bound")
    if guard_op in ("==", "!="):
        return ("countdown-while",
                f"a while loop whose test `{_show_node(shape.guard)}` is an "
                f"equality, and the counter is stopped by hitting it")
    return ("affine-while", f"a while loop whose test "
                            f"`{_show_node(shape.guard)}` this layer read")


def _first(text, ch):
    i = text.find(ch)
    return text[max(0, i - 8):i + 8] if i >= 0 else ch


# ── one loop's verdict ───────────────────────────────────────────────────────

class LoopVerdict:
    """Everything one loop produced: its shape, its candidates, its verdicts.

    `status` is the roll-up over `obligations`, and the rule is stated rather
    than left to a reader:

      REFUTED  any obligation's Lean theorem was refuted, or the bounded search
               found a state at which a candidate fails;
      PROVED   every emitted obligation was closed by Lean, and there was at
               least one;
      UNKNOWN  anything else — including a loop with no candidate at all,
               whose `no-candidate` obligation is UNKNOWN with the store named;
      SKIPPED  no loop was read.

    So `PROVED` cannot be reached by a loop with nothing to say, and it cannot
    be reached by a loop whose synthesis was never asked.
    """

    __slots__ = ("fn", "index", "family", "why_family", "shape", "rel",
                 "invariants", "variants", "obligations", "status", "candidates",
                 "every", "proof", "header", "lean_detail", "precondition")

    #: The slots that default to an empty LIST rather than to None, because a
    #: consumer iterates them.  Named here so adding a slot is a decision
    #: rather than an accident: a slot that defaults to None and is iterated is
    #: a crash in the report, which is the one place this module must not have
    #: one.
    _LISTS = ("invariants", "variants", "obligations", "candidates", "every",
              "proof", "header")


    def __init__(self, **kw):
        for slot in self.__slots__:
            setattr(self, slot, kw.get(slot) or ([] if slot in self._LISTS
                                                  else None))
        if self.status is None:
            self.status = UNKNOWN

    @property
    def ok(self):
        return self.status in (PROVED, SKIPPED)

    def counts(self):
        out = {}
        for ob in self.obligations:
            out[ob.status or UNKNOWN] = out.get(ob.status or UNKNOWN, 0) + 1
        return out

    def summary(self):
        c = self.counts()
        total = sum(c.values())
        return (f"{getattr(self.fn, 'name', '?')}: {self.status.upper()} — "
                f"{c.get(PROVED, 0)}/{total} obligation(s) closed by Lean"
                + (f", invariant `{self.invariants[0].text}`"
                   if self.invariants else ", no affine invariant")
                + (f", variant `{self.variants[0].text}`"
                   if self.variants else ", no decreasing affine variant")
                + (f", under the synthesised precondition "
                   f"`{self.precondition}`" if self.precondition else "")
                + f" [{self.family}]")

    def __repr__(self):
        return f"LoopVerdict({getattr(self.fn, 'name', '?')}, {self.status!r})"


def check_function(fn, source="<source>", lean=None, text=None):
    """One function's loop verdicts, synthesis plus (optionally) one Lean run.

    `lean` is a callable `(proof_path_text, line_index) -> (detail, ok)` or
    None.  It is passed in rather than run here for the reason
    `formal/contracts.py::check_source` gives: `formal/lean.py::run_lean` is the
    ONE launcher in this tree, with the bounds on it, and a checker that
    spawned its own would be a second one with its own bounds.  A caller
    without a Lean binary gets every obligation at UNKNOWN, which is the honest
    answer and NOT a pass.
    """
    out = []
    for shape in loop_shapes(fn):
        out.append(check_loop(shape, source, lean=lean))
    return out


def check_loop(shape, source="<source>", lean=None):
    """One loop: read it, synthesise, discharge, roll up."""
    if not shape.usable:
        ob = Obligation(
            f"{getattr(shape.fn, 'name', '?')}_loop{shape.index}_unreadable",
            "no-candidate", "True", [], [], [],
            why=("this loop is not one this layer's obligations are about: "
                 + shape.unusable))
        ob.status = UNKNOWN
        ob.detail = shape.unusable
        return LoopVerdict(fn=shape.fn, index=shape.index,
                           family="unreadable",
                           why_family=shape.unusable, shape=shape, rel=None,
                           invariants=[], variants=[], obligations=[ob],
                           status=UNKNOWN)
    rel = Relation(shape)
    obligations, invs, variants, every_inv, every_var, precondition = \
        build_obligations(shape, rel, source)
    family, fwhy = family_of(shape)
    # The bounded search first, so a candidate Lean cannot check still gets a
    # REFUTED verdict rather than an UNKNOWN one, and a search that skips is a
    # skip rather than agreement.
    searched = []
    for cand in list(every_inv) + list(every_var):
        witness, skipped = refute(shape, rel, cand)
        cand_search = {"candidate": cand.text, "role": cand.role,
                       "witness": witness, "skipped": skipped}
        searched.append(cand_search)
        if witness is not None:
            _attach_witness(obligations, cand, witness)
    header = _file_header(shape, rel, source, family, fwhy, every_inv,
                          every_var, invs, variants)
    text_out, index = proof_text(obligations, header)
    lean_detail = ""
    if lean is not None and obligations:
        lean_detail, _ok = lean(text_out, index)
        read_lean_verdicts(text_out, lean_detail, index, obligations)
    for ob in obligations:
        if ob.status is None:
            ob.status = UNKNOWN
            ob.detail = (self_reason(ob) if ob.refusal else
                         "no Lean run, so no obligation here was closed by "
                         "the ladder; this is the honest answer and it is not "
                         "a pass")
    verdict = LoopVerdict(fn=shape.fn, index=shape.index, family=family,
                          why_family=fwhy, shape=shape, rel=rel,
                          invariants=invs, variants=variants,
                          obligations=obligations, status=None,
                          candidates=searched, precondition=precondition,
                          every={"invariants": every_inv,
                                 "variants": every_var},
                          proof=text_out, header=header,
                          lean_detail=lean_detail)
    verdict.status = _roll_up(obligations)
    return verdict


def _attach_witness(obligations, cand, witness):
    """Point every obligation about this candidate at the counterexample.

    Only the obligations that CANDIDATE appears in.  A refutation found for
    `total = i` says nothing about `total = 2 * i`, and marking the whole loop
    REFUTED from one candidate would make the report name a theorem it has not
    looked at.
    """
    said = (f"the bounded search reached a state at which `{cand.text}` is "
            f"{witness['form']} against the claimed {witness['claimed']}, "
            f"after {witness['iterations']} iteration(s) from the entry value "
            f"{witness['input']}")
    for ob in obligations:
        if ob.candidate is not cand:
            continue
        ob.witness = witness
        if ob.status in (None, PROVED, UNKNOWN):
            ob.status = REFUTED
            ob.detail = said


def _roll_up(obligations):
    """The loop's one-line verdict, and the rule is stated rather than guessed.

      REFUTED  any obligation's candidate has a counterexample;
      PROVED   every obligation about the invariant and the variant closed, AND
               at least one `var-post` closed — the loop's VALUE is named and
               proved.  A loop with no invariant at all has no closable post, so
               it cannot be PROVED, which is the honest reading: its termination
               may be proved and its value is not determined;
      UNKNOWN  anything else.

    **The post obligations are the one group where any member closing is
    enough**, and the reason is that a loop's answer is one of several CANDIDATE
    answers, not several claims: `c = n`, `c = i`, `c = 0` are three guesses at
    the same thing, and the first one that closes is the answer while the others
    are misses.  Requiring all of them would make a fully proved loop UNKNOWN
    for having offered a second guess.
    """
    if not obligations:
        return UNKNOWN
    if any(ob.status == REFUTED for ob in obligations):
        return REFUTED
    others = [ob for ob in obligations if ob.role != "var-post"]
    posts = [ob for ob in obligations if ob.role == "var-post"]
    if any(ob.status != PROVED for ob in others):
        return UNKNOWN
    if not posts:
        return PROVED
    return PROVED if any(ob.status == PROVED for ob in posts) else UNKNOWN


def _file_header(shape, rel, source, family, fwhy, every_inv, every_var,
                 chosen_inv, chosen_var):
    fn_name = getattr(shape.fn, "name", None) or "<fn>"
    lines = ["/-!",
             f"# Loop invariants and variants synthesised for `{fn_name}`'s "
             f"loop {shape.index}", "",
             f"    The loop: `{shape.describe()}`  ({family}: {fwhy})",
             f"    Source: {source}",
             f"    The loop's scalar variables: {', '.join(rel.names)}",
             f"    The body assigns linearly in EVERY branch: "
             f"{', '.join(rel.changes) or 'nothing'}",
             f"    Body branches: {shape.branches}"]
    if rel.shape.blocked:
        for nm in sorted(rel.shape.blocked):
            lines.append(f"    NOT a linear form here: `{nm}` — "
                         f"{rel.shape.blocked[nm]}")
    if every_inv:
        lines.append("    Synthesised invariant(s): "
                     + "; ".join(f"`{c.text}`" for c in every_inv)
                     + f"  — discharged: "
                     + (f"`{chosen_inv[0].text}`" if chosen_inv else "none"))
    else:
        lines.append("    Synthesised invariant(s): NONE — "
                     + _no_candidate_reason(shape, rel))
    if every_var:
        lines.append("    Synthesised variant(s): "
                     + "; ".join(f"`{c.text}` (drops {abs(c.drop)})"
                                 for c in every_var)
                     + f"  — discharged: "
                     + (f"`{chosen_var[0].text}`" if chosen_var else "none"))
    else:
        lines.append("    Synthesised variant(s): NONE — "
                     + _no_candidate_reason(shape, rel))
    for cand in chosen_var:
        pre, _form, why = precondition_text(rel, cand)
        lines.append(f"    SYNTHESISED PRECONDITION, the premise every "
                     f"obligation below is read under: {pre or 'none'}"
                     + (f"  ({why})" if why and not pre else ""))
    lines.extend(["",
                  "    These are claims about the loop's OWN arithmetic, read",
                  "    from the source and stated over `Int` (a SIGNED reading of",
                  "    the program's word).  They are NOT claims about the",
                  "    machine: `formal/arm64_proof_gen.py` owns that chain.",
                  "-/"])
    return "\n".join(lines)


# ── the report ───────────────────────────────────────────────────────────────

def report_lines(verdicts, verbose=False):
    """One line per loop and one per obligation, in that order.

    A reader's two questions are "what did this find" and "what did it not
    decide", so the per-loop line names the candidates in one clause and the
    per-obligation lines follow in emission order.  Every obligation gets a
    line in either verbosity: an obligation with no line is an obligation whose
    status a reader cannot see, and this module's whole argument is that a
    status nobody can see is a status nobody checked.
    """
    out = []
    for v in verdicts:
        out.append(v.summary())
        for ob in v.obligations:
            out.append(f"    {ob.status or UNKNOWN:<8} {ob.role:<11} "
                       f"{ob.name}")
            out.append(f"             {ob.why}")
            if ob.detail:
                out.append(f"             {ob.detail}")
            if ob.witness:
                out.append(f"             witness: {ob.witness}")
            if verbose and ob.theorem:
                for line in ob.theorem.split("\n"):
                    out.append(f"             | {line}")
    return out


def render(verdicts, verbose=False):
    """`report_lines`, as one string with a trailing newline."""
    return "\n".join(report_lines(verdicts, verbose)) + "\n"


def ledger_rows(verdicts, source_sha256, arch="arm64", lean_version=""):
    """The measured per-obligation ledger, as plain dicts.

    Plain dicts for the reason `formal/build.py::_search_contracts` gives: the
    consumer is usually another process reading a committed JSON, and an object
    whose class gains a field comes back from `json.load` as a dict anyway.

    Every row carries the loop's FAMILY, its candidate's text, the obligation's
    ROLE and its status, so a regression diff says which SHAPE regressed rather
    than only that a theorem stopped closing.
    """
    rows = []
    for v in verdicts:
        base = {"fn": getattr(v.fn, "name", "?"), "loop": v.index,
                "family": v.family, "arch": arch,
                "source_sha256": source_sha256, "lean": lean_version,
                "status": v.status,
                "invariant": v.invariants[0].text if v.invariants else None,
                "variant": v.variants[0].text if v.variants else None}
        for cand in v.candidates:
            base.setdefault("search_skipped", cand["skipped"])
        for ob in v.obligations:
            row = dict(base)
            row.update({"role": ob.role, "obligation": ob.name,
                        "status": ob.status or UNKNOWN,
                        "why": ob.why,
                        "detail": ob.detail[:400]})
            if ob.witness:
                row["witness"] = {k: str(vv) for k, vv in ob.witness.items()}
            rows.append(row)
    return rows


# ── the driver, for the tests and for `formal/build.py` ──────────────────────

def synthesize(source, name=None, text=None):
    """The loop verdicts for one source, WITHOUT running Lean.

    Every obligation comes back UNKNOWN with "no Lean run" — which is the honest
    answer and is what a caller with no toolchain gets, and what
    `formal/build.py` publishes on a default build.  It is deliberately not
    SKIPPED: the synthesis DID happen and DID find candidates, and reporting
    that as "nothing to check" would be the silence this module exists to
    remove.
    """
    mod = F.Parser(F.py_tokenize(source)).parse_module()
    out = []
    for fn in [s for s in mod if type(s).__name__ == "FunctionDef"]:
        out.extend(check_function(fn, name or "<source>", lean=None))
    return out


def lean_runner(lean_bin, lib_dir=None, cwd=None, wall_s=None):
    """A `(text, index) -> (detail, ok)` callable, via `formal/lean.py`.

    `run_lean` is the ONE launcher in this tree and it carries the wall, CPU,
    memory and heartbeat bounds; this function is a THREAD over it and adds
    none of its own, for the reason `formal/contracts.py::check_source` gives
    for accepting `lean_ok` as an argument.  The `.lean` file is written into
    `formal/lean.py::scratch_dir`, which is the only place a generated file may
    live, and the verdict goes through `formal/lean.py`'s own CAS so a repeat
    run costs nothing.
    """
    if not lean_bin:
        return None
    from formal import lean as L

    def run(text_out, index):
        with L.scratch_dir("loopinv") as scratch:
            path = os.path.join(scratch, "loop_invariants.lean")
            with open(path, "w") as f:
                f.write(text_out)
            res = L.run_lean(lean_bin, [os.path.abspath(path)], cwd=cwd,
                             env=dict(os.environ,
                                      LEAN_PATH=lib_dir) if lib_dir else None,
                             wall_s=wall_s)
            detail = (res.stdout or "") + (res.stderr or "")
            if res.exceeded:
                detail += f"\nformal/lean.py::run_lean: {res.exceeded}"
            return detail, res.returncode == 0

    return run
