"""CONTRACTS IN THE SOURCE LANGUAGE: what a program says about itself, and
whether the machine keeps the promise.

WHAT THIS IS
------------
A program can now state a precondition and a postcondition on a function, in
the same expression subset the backend already compiles:

    @requires(n >= 0)
    @ensures(result >= 0)
    def fact(n):
        if n == 0:
            return 1
        else:
            return n * fact(n - 1)

and this module turns that text into a Lean theorem `fact_contract`:

    theorem fact_contract (n : UInt64) :
      (n ^^^ F) >= (0 ^^^ F) ->
      ((fact_go n) ^^^ F) >= (0 ^^^ F)

Two lowerings, and they are deliberately separate because they answer
different questions:

  * `contract_theorems` emits the theorem and NOTHING ELSE.  Whether it holds
    is for Lean to say.  A contract that does not hold is a BUILD FAILURE,
    which is the whole point of writing it down: the promise becomes a claim
    the toolchain can refuse.
  * `instrument` lowers the same clauses into runtime checks, for
    `fire.py build --formal --check-contracts`.  That answers a different
    question -- "does THIS run, at THIS input, keep the promise" -- and is
    the one that catches a contract which is true of the model and false of
    the bytes.

THE FOUR VERDICTS, AND WHY THERE ARE FOUR
-----------------------------------------
A contract checker that reports two answers (holds / does not hold) is a
checker that cannot tell "false" from "I could not decide", and every
project bug in `bugs/` about a `sorry` over a false statement is that
confusion.  So `classify` reports one of four, never a silent pass:

    PROVED    Lean accepted the theorem with 0 holes.
    REFUTED   a bounded search found a concrete input that SATISFIES the
              precondition and VIOLATES the postcondition, evaluated in
              Python over the same model the Lean theorem talks about.  The
              counterexample is a word and a value, so it can be re-run.
    UNKNOWN   the ladder did not close the goal AND the search found
              nothing.  This is a real answer ("the tools here cannot tell"),
              and it is the answer for any clause whose body shape the
              model does not reach -- which is why it must be LOUD.
    SKIPPED   there was no contract to check.  Reported as its own verdict so
              a caller can tell "green because it holds" from "green
              because nothing was written down".

THE BOUNDED SEARCH IS NOT A PROOF, AND IS NOT MEANT TO BE ONE
------------------------------------------------------------
`search_counterexample` proves nothing.  It runs the SOURCE-level model on a
finite set of inputs (the interesting ones plus a small range) and reports
the first violation.  Its job is to make a REFUTED verdict actionable -- a
false contract reported as "false" with no witness is a support ticket, and
one reported as "false, at n = 7 where the model returns -3" is a bug fix.
Its limits are stated rather than hidden: it explores a FINITE set, so a
contract that holds on every input it tried and fails at 10^18 is UNKNOWN,
not PROVED.  `PROVED` can only come from Lean, and `classify` is written so
that no path reaches PROVED without Lean having accepted the goal.

WHY THE EXPRESSION SUBSET IS THE MODEL'S, NOT A SECOND ONE
----------------------------------------------------------
The clauses are lowered by `Clause.lean`, which reads the same AST nodes the
semantic model reads (`formal/arm64_proof_gen.py`'s `_gen_go`) and renders
them with the SAME conventions `_dylib_spec_lean` established: a comparison
is SIGNED, spelled `(a ^^^ 0x8000000000000000) < (b ^^^ 0x8000000000000000)`,
because that is what the CODE computes and what CPython means for an `Int`.

A second spelling of a comparison would be a claim about a comparison the
program never wrote.  Measured on the tree: `(n if n > 3 else 0) * 3` at
`n = 2^63` answers 0, which is the SIGNED reading and not the unsigned one --
so an unsigned spelling of `>` would make `absval`'s contract about a
different function, and the theorem would still typecheck.

WHAT IS A NAME IN A CLAUSE
--------------------------
The parameters of the function, plus `result` in an `@ensures`.  `result` is
the returned WORD, which is what the backend computes and what an `Int` is;
it is not a Python object and there is nothing else it could mean on a target
where every value is one word.  A name that is neither is a REFUSAL, not a
silent 0: a contract that mentions a name the model cannot resolve is a
contract nobody checked, and FORMAL.md's whole subject is that this must be
loud.

WHY `@spec(...)` IS NOT READ HERE
---------------------------------
`@spec(f_spec; f_spec 0 = 1; ...)` (`formal/examples/{fact,fib,sum,count}.mojo`)
is a `;`-separated EQUATION specification -- juxtaposed application and a
bare `=` in operator position, which is not Mojo expression syntax at all
(`fire_compiler.DecoratorArgs` and `Parser._parse_decorator_args` are the
reason it parses).  It names a recursive function over its own symbol and is
read by the recursion contract work, not by this one.  Reading it here would
need a second grammar, and a clause this module accepted without a model to
evaluate it against would be a claim about nothing.

The `@require` / `@ensure` SINGULAR spellings in those same four examples are
this module's: they are the same clauses as the plural, and both are accepted
because both are already in the corpus and a checker that honoured one
spelling would report those four files as contract-free when they are not.
"""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fire_compiler as F  # noqa: E402

# The decorator names that carry a contract, in BOTH spellings.  See the module
# docstring's last section: the singular pair is in the corpus already, and a
# reader that honoured only the plural would call those four files
# contract-free.
REQUIRES_NAMES = frozenset({"requires", "require"})
ENSURES_NAMES = frozenset({"ensures", "ensure"})

# The `# requires:` / `# ensures:` comment pragma.  Offered by the task as the
# fallback for a front end that cannot parse a decorator's arguments; this one
# CAN (`_parse_decorator_args` builds a `CallExpr` for a region with no
# top-level `;`, pinned by `test_examples_parse.py`'s
# `parameterised_decorator_is_a_CallExpr`), so the decorator is the primary
# spelling and this is the second.  Both reach `Clause` by the same reader, so
# a file may use either or both.
PRAGMA_RE = re.compile(r"^\s*#\s*(requires|ensures)\s*:\s*(.+?)\s*$")

# Comparisons a clause may use, and the sign mask they are rendered with.  Both
# are `_dylib_spec_lean`'s values, imported through it rather than re-spelled,
# so a clause and a derived export spec cannot disagree about what `>` means.
_COMPARISONS = ("==", "!=", "<", "<=", ">", ">=")
_SIGN_FLIP = "0x8000000000000000"

# UInt64 arithmetic as Lean spells it.  `UInt64.div` / `UInt64.mod` rather than
# a bare `/` or `%`, which on `UInt64` is not the truncating operation -- the
# same table `_dylib_spec_lean` uses, reached through it.
_ARITH_OPS = {"+", "-", "*", "/", "%"}

# The verdict set.  Named constants rather than bare strings because
# `classify` and every consumer have to agree on the SPELLING, and a typo in a
# verdict is a silent skip -- the exact failure this module exists to prevent.
PROVED = "proved"
REFUTED = "refuted"
UNKNOWN = "unknown"
SKIPPED = "skipped"

# Inputs the bounded search always tries, before any range.  A contract about
# `abs` is violated at the sign boundary and nowhere else in 0..64, and a
# search that only walked 0..64 would say UNKNOWN about the one case a reader
# would check by hand.  These are the boundaries a word arithmetic can break
# at: the signed interpretation's limits, the unsigned limits, and the two
# small values either side of each.
BOUNDARY_INPUTS = (
    0, 1, 2, 3, 4, 5,
    (1 << 16) - 1, 1 << 16,
    (1 << 31) - 1, 1 << 31, (1 << 31) + 1,
    (1 << 32) - 1, 1 << 32,
    (1 << 63) - 1, 1 << 63, (1 << 63) + 1,          # the SIGN boundary
    (1 << 64) - 2, (1 << 64) - 1,
)

# And the small range walked after them, so a contract that is false at some
# ordinary `n` is refuted rather than reported UNKNOWN.
SEARCH_RANGE = 64

# The step budget for one search and one source evaluation, so an unbounded
# model raises rather than hangs.  A search that never finishes is a search
# that never reports, and the verdict for that is UNKNOWN -- which is reached
# by raising and being caught, not by waiting.
SEARCH_FUEL = 200000

# A derived clause's Lean source, above which it is not emitted.  The same
# bound and the same reason as `_dylib_spec_lean`'s: the ladder runs `simp`
# and `decide` over what is emitted, and a term past this is a term the tools
# time out on.  Returning None ("no clause") is the honest response -- an
# UNKNOWN verdict with a reason beats a UNKNOWN verdict with a hang.
MAX_LEAN_CHARS = 4000


class ContractError(Exception):
    """A contract this module refuses to lower, with the sentence to print.

    Distinct from a Lean failure on purpose: this is a DECISION about the
    source (a name that does not resolve, an operator with no rendering),
    and it is reported before any tool runs.  A caller that turns it into a
    build refusal is right; a caller that turns it into UNKNOWN is also
    right, but must say so.
    """


class Clause:
    """One `@requires` / `@ensures` clause, as written.

    `name` is the decorator or pragma name the reader found it under, kept
    verbatim so a message can quote what the source said rather than what this
    module would have called it.  `expr` is the parsed AST node -- the front
    end's own parse, not a re-parse -- or None when the clause came from a
    comment pragma, which is text and has to be parsed here.

    `source` / `line` are where to go and look, for the reason
    `formal/admitted.py`'s `Contract` carries them.
    """

    __slots__ = ("name", "expr", "text", "source", "line", "is_pragma")

    def __init__(self, name, expr, text, source, line, is_pragma):
        self.name = name
        self.expr = expr
        self.text = " ".join((text or "").split())
        self.source = source
        self.line = line
        self.is_pragma = is_pragma

    @property
    def kind(self) -> str:
        """`requires` or `ensures`, whichever SPELLING this one used.

        Normalised, so a consumer compares against one pair of words rather
        than the four decorator names.
        """
        return "requires" if self.name in REQUIRES_NAMES else "ensures"

    def __repr__(self):
        return (f"Clause({self.kind}, {self.text!r}, {self.source}:{self.line})")


class Contract:
    """What one function promises: its preconditions and its postconditions.

    `requires` and `ensures` are lists because a source may write more than
    one, and ANDing them is the only reading that makes a second clause mean
    anything -- `@requires(a) @requires(b)` is a weaker promise than either
    alone, which is what a reader expects and what `eval` below computes.

    An empty pair is NOT a contract: `Contract.requires == [] and
    Contract.ensures == []` means the file said nothing, and every consumer
    here reports that as SKIPPED rather than as a green proof.
    """

    __slots__ = ("name", "requires", "ensures", "source", "line")

    def __init__(self, name, requires, ensures, source, line):
        self.name = name
        self.requires = list(requires)
        self.ensures = list(ensures)
        self.source = source
        self.line = line

    @property
    def clauses(self) -> list:
        return list(self.requires) + list(self.ensures)

    def __bool__(self):
        return bool(self.requires or self.ensures)

    def __repr__(self):
        return (f"Contract({self.name}, requires={self.requires!r}, "
                f"ensures={self.ensures!r})")


# ── reading the source ────────────────────────────────────────────────────────

def _decorator_name(deco):
    """The bare name a decorator names, from the spellings that can carry one.

    A bare `@deco` is the string; `@requires(n >= 0)` is a `CallExpr`
    (`fire_compiler.DecoratorArgs` only for a `;`-separated region, which a
    contract clause is not); an `@IdentExpr` arrives from the dataclass
    rewrites.  Three spellings, one reader, so a clause cannot be honoured
    under one of them and dropped under another -- which is a bug this
    project has already paid for once (`formal/model.py::_decorator_name`'s
    own note).
    """
    if isinstance(deco, str):
        return deco
    if isinstance(deco, F.IdentExpr):
        return getattr(deco, "name", None)
    if isinstance(deco, F.CallExpr):
        func = getattr(deco, "func", None)
        if isinstance(func, F.IdentExpr):
            return getattr(func, "name", None)
    return None


def _is_contract_name(name) -> bool:
    return bool(name) and (name in REQUIRES_NAMES or name in ENSURES_NAMES)


def _clause_from_expr(name, call, source, line):
    """A clause from a `@name(expr)` decorator, or None when it is not one.

    None is returned for a BARE `@requires` (no argument list) rather than a
    refusal: there is nothing to check, and refusing would make a file that
    mentions the word unbuildable for no claim.  The caller counts those and
    reports them, so the file is not silently treated as contract-free.
    """
    args = list(getattr(call, "args", None) or [])
    kwargs = list(getattr(call, "kwargs", None) or [])
    if not args:
        raise ContractError(
            f"`@{name}` takes the clause as its argument, and got none: "
            f"there is nothing to state, and a clause with no expression "
            f"would be a check that can never fail")
    if len(args) > 1:
        raise ContractError(
            f"`@{name}` takes ONE clause, and got {len(args)}; write them as "
            f"separate `@{name}` decorators")
    if kwargs:
        names = [k for k, _v in kwargs]
        raise ContractError(
            f"`@{name}` takes its clause positionally, and got keyword "
            f"{names}: a named clause is a different annotation from a "
            f"predicate over the parameters")
    return Clause(name, args[0], None, source, line, False)


def _parse_pragma_text(text, source, line):
    """Parse a `# requires:` pragma's text with the FRONT END's own parser.

    Not `eval`, not a hand-written reader.  The clause is in the same
    expression subset the backend compiles, so the one parser that compiles
    it is the one that reads it -- a second grammar would be free to accept
    something the backend refuses, and then the contract would be about a
    program nobody can build.

    The parse is wrapped so a source comment cannot reach the exception path:
    a `#` inside a string literal is not a pragma, and `parse_module` on a
    fragment that happens to be one line of a larger expression is not a
    statement list.
    """
    try:
        mod = F.Parser(F.py_tokenize(text)).parse_module()
    except Exception as exc:
        raise ContractError(
            f"{source}:{line}: the `# requires:` / `# ensures:` clause "
            f"{text!r} does not parse as an expression ({exc}); it is in the "
            f"same subset the backend compiles, so a clause outside it has no "
            f"model to be checked against")
    if len(mod) != 1 or type(mod[0]).__name__ != "ExprStmt":
        raise ContractError(
            f"{source}:{line}: the `# requires:` / `# ensures:` clause "
            f"{text!r} is not a single expression")
    return mod[0].value


def read_contracts(fn, source="<source>", text=None) -> Contract:
    """What `fn` promises, from its decorators and from comment pragmas.

    `text` is the function's own source text, and it is OPTIONAL because the
    pragma reader is a fallback: a function with only decorators needs no
    source, and every consumer in this tree already has an AST and not a
    source string.  Passing it is what lets `# requires:` be honoured.

    A function with neither decoration yields an EMPTY `Contract`, and
    `bool()` of that is False -- the difference every consumer needs between
    "promised nothing" and "promised something", because a checker that
    treats them alike reports a contract-free file as green for a reason that
    has nothing to do with the contract.
    """
    name = getattr(fn, "name", None) or "<function>"
    line = getattr(fn, "line", 0) or 0
    requires, ensures = [], []
    for deco in (getattr(fn, "decorators", None) or []):
        dname = _decorator_name(deco)
        if not _is_contract_name(dname):
            continue
        clause = _clause_from_expr(dname, deco, source, line)
        (requires if clause.kind == "requires" else ensures).append(clause)
    if text is not None:
        for offset, raw in enumerate(text.splitlines()):
            m = PRAGMA_RE.match(raw)
            if not m:
                continue
            kw, clause_text = m.group(1), m.group(2)
            expr = _parse_pragma_text(clause_text, source, line + offset)
            clause = Clause(kw, expr, clause_text, source, line + offset, True)
            (requires if clause.kind == "requires" else ensures).append(clause)
    return Contract(name, requires, ensures, source, line)


# ── reading a clause: one IR, two printers ───────────────────────────────────
#
# A clause is read ONCE into a small typed IR, and then printed twice: as Lean
# source for the theorem, and as a Python closure for the bounded search.
#
# The alternative -- a Lean renderer and a Python evaluator written side by side
# -- is the one this project has been bitten by in three other places (the
# spec's `go`/`go_cond`, the x86-64 and arm64 `_eval_eq_mojo`, the dylib and
# per-export specs).  Each pair is two readings of one AST, and a pair that
# disagrees does not fail: it makes a REFUTED verdict about a function nobody
# wrote, which is the exact "a `sorry` over a false statement" shape
# `lib/Contracts.lean`'s docstring warns about at length.  With one reader the
# two backends can only agree.


class _Op:
    """One IR node kind.  Named rather than a bare tuple tag, because the tag is
    what both printers dispatch on and an unlabelled string is where a third
    backend would be added by copy rather than by adding one `elif`."""

    LIT = "lit"        # a word constant: (LIT, v)
    VAR = "var"        # a parameter, or `result`: (VAR, name)
    NEG = "neg"        # word negation: (NEG, e)
    POS = "pos"        # unary `+`, which is the identity: (POS, e)
    INVERT = "inv"     # `~`: (INVERT, e)
    ARITH = "arith"    # (ARITH, op, a, b) for + - * / %
    CMP = "cmp"        # (CMP, op, a, b) for the six comparisons
    AND = "and"        # (AND, a, b)
    OR = "or"          # (OR, a, b)
    NOT = "not"        # (NOT, e)
    TRUTHY = "truthy"  # a VALUE used as a condition: (TRUTHY, e)
    ITE = "ite"        # (ITE, cond, then, else)
    SEL = "sel"        # (SEL, cond, then, else) -- a builtin lowered to a choice
    ABS = "abs"        # (ABS, e)
    MIN = "min"        # (MIN, a, b)
    MAX = "max"        # (MAX, a, b)
    CLAMP = "clamp"    # (CLAMP, x, lo, hi)


def _sign_flip(v):
    """Flip the SIGN BIT, which is what makes a `UInt64` order signed.

    Both backends use this one function rather than each spelling the
    constant: the Lean printer emits `(x ^^^ 0x8000...)` and the evaluator
    computes `v ^ (1 << 63)`, and those two are the same statement only
    because this is one function.  Measured on the tree: `(n if n > 3 else 0)
    * 3` at `n = 2^63` answers 0, which is the SIGNED reading and not the
    unsigned one -- so a pair that disagreed here would be a checker
    evaluating a different `>` than the compiler emits, on exactly the inputs
    where signedness matters.
    """
    return v ^ (1 << 63)


def _signed(v):
    """A `UInt64` word read as a signed integer, the reading CPython means for
    an `Int`.  Python's `int` is unbounded, so this is the one place the
    wraparound has to be undone explicitly, and doing it in one function is
    what keeps the two backends on the same reading."""
    return v - (1 << 64) if v >= (1 << 63) else v


class _Reader:
    """One clause's expression, read into the IR.

    Built per clause because it carries the NAME ENVIRONMENT: the function's
    parameters, plus `result` in an `@ensures`.  A name outside that set
    reads as None -- a refusal, not a silent 0, for the reason the module
    docstring gives.

    `result_term` is an IR node substituted for the `result` name in an
    `@ensures`.  It is a NODE rather than Lean text precisely so the evaluator
    gets the model's value and not the string `fact_go n`; a Lean-text
    substitution would make the bounded search evaluate a name it has no
    definition for, which is the whole class of bug this split exists to
    prevent.
    """

    BUILTINS = {"abs": (_Op.ABS, 1), "min": (_Op.MIN, 2),
                "max": (_Op.MAX, 2), "clamp": (_Op.CLAMP, 3)}

    def __init__(self, names, result_term=None, result_name="result"):
        self.names = set(names)
        self.result_name = result_name
        self.result_term = result_term
        if result_name:
            self.names.add(result_name)

    # -- values ---------------------------------------------------------
    def value(self, node):
        kind = type(node).__name__
        if kind == "IntLiteral":
            v = getattr(node, "value", None)
            if v is None:
                raw = getattr(node, "raw", None)
                if raw is None:
                    return None
                try:
                    v = int(raw, 0)
                except ValueError:
                    return None
            return (_Op.LIT, v & ((1 << 64) - 1))
        if kind == "IdentExpr":
            nm = getattr(node, "name", None)
            if nm == self.result_name and self.result_term is not None:
                return self.result_term
            return (_Op.VAR, nm) if nm in self.names else None
        if kind == "UnaryOp":
            op = getattr(node, "op", None)
            tag = {"-": _Op.NEG, "+": _Op.POS, "~": _Op.INVERT}.get(op)
            if tag is None:
                return None
            inner = self.value(getattr(node, "operand", None))
            return None if inner is None else (tag, inner)
        if kind == "BinaryOp":
            op = getattr(node, "op", None)
            if op in ("and", "or"):
                # Short-circuit, kept as an ITE over the left operand's
                # TRUTHINESS -- which is what Python defines and what
                # `_emit_truthy_word` computes.  Flattening it to
                # "both sides nonzero" would be a different function.
                a_val = self.value(getattr(node, "left", None))
                a_test = self.truth(getattr(node, "left", None))
                b_val = self.value(getattr(node, "right", None))
                if a_val is None or a_test is None or b_val is None:
                    return None
                return ((_Op.ITE, a_test, b_val, a_val) if op == "and"
                        else (_Op.ITE, a_test, a_val, b_val))
            if op in _COMPARISONS:
                a = self.value(getattr(node, "left", None))
                b = self.value(getattr(node, "right", None))
                if a is None or b is None:
                    return None
                return (_Op.CMP, "=" if op == "==" else op, a, b)
            if op in _ARITH_OPS:
                a = self.value(getattr(node, "left", None))
                b = self.value(getattr(node, "right", None))
                if a is None or b is None:
                    return None
                return (_Op.ARITH, op, a, b)
            return None
        if kind == "TernaryExpr":
            test = self.truth(getattr(node, "condition", None))
            then = self.value(getattr(node, "then_val", None))
            other = self.value(getattr(node, "else_val", None))
            if test is None or then is None or other is None:
                return None
            return (_Op.ITE, test, then, other)
        if kind == "CallExpr":
            return self.builtin(node)
        return None

    # -- builtin calls --------------------------------------------------
    #
    # `abs` / `min` / `max` / `clamp` are the four the task names.  They are
    # their OWN IR tags rather than being expanded to ITE here, so both
    # printers can use the natural spelling: the Lean printer renders the
    # selection `omega` can split (the reason the handoff records about
    # `exportFuel` -- `omega` and `decide` work on literals and cannot unfold a
    # library function), and the evaluator runs the Python operation.  Expanding
    # here would force the evaluator to re-derive it from the expansion.
    def builtin(self, node):
        func = getattr(node, "func", None)
        name = func.name if isinstance(func, F.IdentExpr) else None
        spec = self.BUILTINS.get(name)
        if spec is None:
            return None
        tag, arity = spec
        args = list(getattr(node, "args", None) or [])
        if getattr(node, "kwargs", None) or len(args) != arity:
            return None
        vals = [self.value(a) for a in args]
        if any(v is None for v in vals):
            return None
        return (tag,) + tuple(vals)

    # -- propositions ---------------------------------------------------
    def truth(self, node):
        """A PROPOSITION that is true exactly when `node` is TRUTHY.

        The separate reader is what keeps a word-valued condition from being
        read as a word-valued ANSWER: a comparison is already a proposition and
        must NOT be given a `!= 0` around it, because `n > 3 != 0` is a claim
        about a value this module never forms.  That mistake is not
        hypothetical -- it is the difference between `eval_eq_mojo`'s `by_cases`
        hypothesis and its goal's `if` test, and ten of the forty-five examples
        were unprovable over it.
        """
        kind = type(node).__name__
        if kind == "UnaryOp" and getattr(node, "op", None) == "not":
            inner = self.truth(getattr(node, "operand", None))
            return None if inner is None else (_Op.NOT, inner)
        if kind == "BinaryOp":
            op = getattr(node, "op", None)
            if op in _COMPARISONS:
                a = self.value(getattr(node, "left", None))
                b = self.value(getattr(node, "right", None))
                if a is None or b is None:
                    return None
                return (_Op.CMP, "=" if op == "==" else op, a, b)
            if op in ("and", "or"):
                a = self.truth(getattr(node, "left", None))
                b = self.truth(getattr(node, "right", None))
                if a is None or b is None:
                    return None
                return ((_Op.AND, a, b) if op == "and" else (_Op.OR, a, b))
        val = self.value(node)
        return None if val is None else (_Op.TRUTHY, val)

    def clause_ir(self, clause, params):
        """One clause as an IR proposition, or None when it has no reading.

        `result` stays a plain NAME in the IR.  It is substituted on each
        side separately -- the Lean printer with the model's Lean term, the
        evaluator with the model's VALUE -- and doing it that way rather than
        once in the reader is what keeps the two from needing two forms of the
        model: `_result_term` lives in the proof generator and knows the Lean
        name, `evaluate_source` knows the value, and the IR in between knows
        neither.  One reader, three facts, no module owning two of them.
        """
        return _Reader(params).truth(clause.expr)


def _mentions(node, name) -> bool:
    """Whether `name` occurs anywhere in `node`.  One recursive walk over
    `fire_compiler`'s own dataclasses rather than a per-node-kind visitor,
    because a visitor that forgets a node kind fails by NOT noticing."""
    from formal.model import iter_nodes
    return any(getattr(n, "name", None) == name
               and type(n).__name__ == "IdentExpr"
               for n in iter_nodes(node))


def _lean_of(node, result_text=None) -> str:
    """An IR node as Lean source over `UInt64`.

    `result_text` substitutes for the `result` name; without it a clause that
    mentions `result` renders the bare name, which is a Lean error rather than
    a wrong claim -- the right kind of failure, and one a caller that forgot to
    pass the term gets loudly.
    """
    tag = node[0]
    if tag == _Op.LIT:
        return f"({node[1]} : UInt64)"
    if tag == _Op.VAR:
        if node[1] == "result" and result_text:
            return result_text
        return node[1]
    if tag == _Op.NEG:
        return f"(- {_lean_of(node[1], result_text)})"
    if tag == _Op.POS:
        return _lean_of(node[1], result_text)
    if tag == _Op.INVERT:
        return f"(~~~ {_lean_of(node[1], result_text)})"
    if tag == _Op.ARITH:
        sym = {"+": "+", "-": "-", "*": "*",
               "/": "UInt64.div", "%": "UInt64.mod"}[node[1]]
        return (f"({_lean_of(node[2], result_text)} {sym} "
                f"{_lean_of(node[3], result_text)})")
    if tag == _Op.CMP:
        a, b = _lean_of(node[2], result_text), _lean_of(node[3], result_text)
        return f"(({a}) ^^^ {_SIGN_FLIP}) {node[1]} (({b}) ^^^ {_SIGN_FLIP})"
    if tag in (_Op.AND, _Op.OR):
        word = "∧" if tag == _Op.AND else "∨"
        return (f"({_lean_of(node[1], result_text)} {word} "
                f"{_lean_of(node[2], result_text)})")
    if tag == _Op.NOT:
        return f"(Not {_lean_of(node[1], result_text)})"
    if tag == _Op.TRUTHY:
        return f"({_lean_of(node[1], result_text)}) != 0"
    if tag in (_Op.ITE, _Op.SEL):
        return (f"(if {_lean_of(node[1], result_text)} then "
                f"{_lean_of(node[2], result_text)} else "
                f"{_lean_of(node[3], result_text)})")
    if tag == _Op.ABS:
        x = _lean_of(node[1], result_text)
        lt = f"(({x}) ^^^ {_SIGN_FLIP}) < (0 ^^^ {_SIGN_FLIP})"
        return f"(if {lt} then 0 - {x} else {x})"
    if tag in (_Op.MIN, _Op.MAX):
        a, b = _lean_of(node[1], result_text), _lean_of(node[2], result_text)
        op = "<" if tag == _Op.MIN else ">"
        test = f"(({a}) ^^^ {_SIGN_FLIP}) {op} (({b}) ^^^ {_SIGN_FLIP})"
        return f"(if {test} then {a} else {b})"
    if tag == _Op.CLAMP:
        x = _lean_of(node[1], result_text)
        lo = _lean_of(node[2], result_text)
        hi = _lean_of(node[3], result_text)
        below = f"(({x}) ^^^ {_SIGN_FLIP}) < (({lo}) ^^^ {_SIGN_FLIP})"
        above = f"(({x}) ^^^ {_SIGN_FLIP}) > (({hi}) ^^^ {_SIGN_FLIP})"
        return f"(if {below} then {lo} else if {above} then {hi} else {x})"
    raise ContractError(f"no Lean rendering for the IR tag {tag!r}")


def _eval_of(node, env, fuel=None):
    """An IR node evaluated in Python over `UInt64` semantics.

    Returns an INT for a word and a BOOL for a proposition, and that
    distinction is load-bearing: `TRUTHY` compares the value to zero while
    `CMP` compares two signed readings, and a backend that returned one for
    the other would make `n != 0` and `n == 0` the same question.

    `fuel` is the step budget for a `partial` model, so an unbounded
    recursion raises rather than hanging -- a search that hangs is a search
    that never reaches a verdict, and UNKNOWN is a verdict.
    """
    if fuel is not None and fuel[0] <= 0:
        raise ContractError("the bounded search ran out of its step budget")
    tag = node[0]
    if tag == _Op.LIT:
        return node[1]
    if tag == _Op.VAR:
        name = node[1]
        if name not in env:
            raise ContractError(f"the search evaluated the unbound name {name!r}")
        return env[name]
    if tag == _Op.NEG:
        return (-_eval_of(node[1], env, fuel)) & _MASK
    if tag == _Op.POS:
        return _eval_of(node[1], env, fuel)
    if tag == _Op.INVERT:
        return (~_eval_of(node[1], env, fuel)) & _MASK
    if tag == _Op.ARITH:
        a = _eval_of(node[2], env, fuel)
        b = _eval_of(node[3], env, fuel)
        if node[1] == "+":
            return (a + b) & _MASK
        if node[1] == "-":
            return (a - b) & _MASK
        if node[1] == "*":
            return (a * b) & _MASK
        if node[1] == "/":
            if b == 0:
                # The machine TRAPS on a zero divisor, and the model's own
                # rule for it is a refusal.  A search must not read `x / 0` as
                # 0 -- that is a different function, and it would make a
                # contract about division look satisfiable where the program
                # dies.  Recorded as a refusal, not a value.
                raise ContractError("a clause divides by zero at this input")
            return (a // b) & _MASK
        if node[1] == "%":
            if b == 0:
                raise ContractError("a clause takes a zero modulus at this input")
            return (a % b) & _MASK
    if tag == _Op.CMP:
        a = _signed(_eval_of(node[2], env, fuel))
        b = _signed(_eval_of(node[3], env, fuel))
        op = node[1]
        return {"=": a == b, "!=": a != b, "<": a < b,
                "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    if tag == _Op.AND:
        if fuel is not None:
            fuel[0] -= 1
        return (bool(_eval_of(node[1], env, fuel))
                and bool(_eval_of(node[2], env, fuel)))
    if tag == _Op.OR:
        if fuel is not None:
            fuel[0] -= 1
        return (bool(_eval_of(node[1], env, fuel))
                or bool(_eval_of(node[2], env, fuel)))
    if tag == _Op.NOT:
        return not _eval_of(node[1], env, fuel)
    if tag == _Op.TRUTHY:
        return _eval_of(node[1], env, fuel) != 0
    if tag in (_Op.ITE, _Op.SEL):
        return (_eval_of(node[2], env, fuel) if _eval_of(node[1], env, fuel)
                else _eval_of(node[3], env, fuel))
    if tag == _Op.ABS:
        return abs(_signed(_eval_of(node[1], env, fuel))) & _MASK
    if tag == _Op.MIN:
        return min(_signed(_eval_of(node[1], env, fuel)),
                   _signed(_eval_of(node[2], env, fuel))) & _MASK
    if tag == _Op.MAX:
        return max(_signed(_eval_of(node[1], env, fuel)),
                   _signed(_eval_of(node[2], env, fuel))) & _MASK
    if tag == _Op.CLAMP:
        x = _signed(_eval_of(node[1], env, fuel))
        lo = _signed(_eval_of(node[2], env, fuel))
        hi = _signed(_eval_of(node[3], env, fuel))
        return (lo if x < lo else (hi if x > hi else x)) & _MASK
    raise ContractError(f"no Python evaluation for the IR tag {tag!r}")


_MASK = (1 << 64) - 1

# ── the theorem ──────────────────────────────────────────────────────────────

# THE TACTIC LADDER, and it is the SAME list the emitted script uses.
#
# These four names are not documentation: `contract_theorems` writes them into
# the `first | … | … | …` it emits, and `Verdict.why` prints them back to a
# reader.  They were briefly five, with `bv_decide` listed but NOT emitted, so
# every PROVED verdict claimed a rung the proof never ran -- which is the one
# kind of statement this module exists to stop making.  If a rung is not in the
# script it does not go in this tuple.
#
# The order is measurement:
#   * `simp_all` first: it closes a clause whose model the simplifier can
#     evaluate under the `by_cases` split, which is the common case and the one
#     `eval_eq_mojo` closes for the same shapes.
#   * `omega` second: it closes the linear-arithmetic clauses the simplifier
#     cannot, and it is where a genuinely unprovable contract says so.
#   * `decide` third: a fully concrete goal.
#
# `bv_decide` is DELIBERATELY absent.  It decides `BitVec` goals; `UInt64` is
# `Lean.UInt64`, a `Fin (2^64)`, which is a STRUCTURE and not a bitvector, so on
# a goal in this module it is a category error rather than a weaker tactic --
# the same mistake `bugs/FORMAL_contract_work_handoff.md` §3 records as having
# produced a spurious counterexample on `arm64_reg`.  If a clause over `BitVec`
# is ever wanted, THIS is where it goes, and the note travels with it.
#
# What is NOT here is anything that can leave the goal silently open.  `first`
# takes the first rung that CLOSES it; the last rung is `omega`, whose failure
# is an error, so the script either proves the contract or fails with the
# theorem named.
LADDER = ("simp_all", "omega", "decide")

# How each rung is SPELLED, one place.  `simp_all` is the only one that needs
# the lemma set, and `simp_all` is also the only one whose spelling differs
# from its name (it is `simp_all [...]`, not `simp_all`).  A rung with no entry
# here is written bare, which is right for the other two and would be wrong for
# anything needing a simp set -- so a new rung that needs one has to be added
# here rather than to the `first` block.
_LADDER_LEMMAS = {"simp_all"}


def _ladder_script(simp: str) -> str:
    """The `first | … | … | …` block, generated from `LADDER`.

    Exists so `LADDER` and the emitted script cannot disagree, which they did
    once: `LADDER` named `bv_decide`, the script did not contain it, and every
    PROVED verdict therefore quoted a tactic the proof never ran.
    """
    lines = ["first"]
    for rung in LADDER:
        text = f"{rung} [{simp}]" if rung in _LADDER_LEMMAS else rung
        lines.append(f"    | {text}" if rung not in _LADDER_LEMMAS
                     else f"    | ({text})")
    return "\n".join(lines)


def _result_term(model_name, params) -> str:
    """How the model is APPLIED at these parameters, for `result` in a clause.

    `model_name` applied to the parameter binders, positionally -- the same
    rendering `_call_go` produces, reached through it so the contract's
    `result` and the model's own application cannot drift.
    """
    if not params:
        return model_name
    return f"({model_name} {' '.join(params)})"


class Emission:
    """What `contract_theorems` produced, as more than a string.

    A string is what a caller writes to a file, and a string cannot say
    whether its goal was emitted with the `by_cases` prelude or whether the
    clauses had a rendering at all -- so a caller reading one back could only
    guess, and the guess would be "it closed".  The three fields are the
    three questions a consumer actually has:

      `lean`   the text to write, "" when nothing was emitted;
      `goal`   the proposition, so `classify` can find the theorem in Lean's
               diagnostics by name AND tell an unrelated failure from this one;
      `split`  whether the model's own conditions were case-split.  False
               means the goal was handed to `omega` unsplit, which is a
               statement about this tree's reach and NOT about the contract
               -- so it can never be reported as PROVED.
    """

    __slots__ = ("lean", "goal", "split", "contract", "params", "fn", "model")

    def __init__(self, lean, goal, split, contract, params, fn, model):
        self.lean = lean
        self.goal = goal
        self.split = split
        self.contract = contract
        self.params = list(params)
        self.fn = fn
        self.model = model

    def __bool__(self):
        return bool(self.lean)

    def __str__(self):
        return self.lean

    def __repr__(self):
        return (f"Emission(name={self.contract.name!r}, goal={self.goal!r}, "
                f"split={self.split}, emitted={bool(self.lean)})")


def contract_theorems(contract, params, model_name=None, fn=None,
                      source_note=True):
    """The Lean theorem for one function's contract, as an `Emission`.

    The statement is the SHAPE the task asks for: for all inputs satisfying
    the precondition, the MODEL's result satisfies the postcondition.  It is
    stated over the model (`f_go`) rather than over the machine, because the
    model is the thing derived from the SOURCE and it is what the bounded
    search evaluates; tying the claim to the machine is the per-export work
    `lib/Contracts.lean` already does and re-doing it here would be a second
    implementation of a proved thing.

    `fn` is the function itself, needed for `model_conditions` -- the
    `by_cases` prelude.  A theorem emitted WITHOUT it will not close, and
    `Emission.split` says so, so `classify` can refuse to call that PROVED.

    An `Emission` with `lean == ""` is returned for a function with no
    contract and for one whose clauses have no rendering; `unlowered_reason`
    says which, because "" alone cannot.
    """
    params = list(params)
    model = model_name or f"{contract.name}_go"
    result_term = _result_term(model, params)
    pres, posts = [], []
    for clause in contract.requires:
        ir = _Reader(params).clause_ir(clause, params)
        if ir is not None:
            pres.append(ir)
    for clause in contract.ensures:
        ir = _Reader(params).clause_ir(clause, params)
        if ir is not None:
            posts.append(ir)
    if not contract or (not pres and not posts):
        return Emission("", "", False, contract, params, fn, model)
    binders = " ".join(f"({p} : UInt64)" for p in params) or "(n : UInt64)"
    # The goal.  Every precondition is conjoined, every postcondition is
    # conjoined, and the whole postcondition is IMPLED by the whole
    # precondition -- the shape that makes a false contract a falsifiable
    # statement rather than a conjunction a reader has to unpick.
    pre_text = [_lean_of(p) for p in pres]
    post_text = [_lean_of(p, result_term) for p in posts]
    antecedent = " ∧ ".join(f"({p})" for p in pre_text) if pre_text else "True"
    post = " ∧ ".join(f"({p})" for p in post_text) if post_text else "True"
    goal = f"{antecedent} → ({post})"
    # The hypothesis NAMES the preconditions will carry.  They have to be
    # `intro`d and, where there is more than one, SPLIT -- and this is the
    # whole difference between a contract the ladder closes and one it cannot.
    #
    # It did not `intro` at all, so the preconditions were never in context:
    # `simp +decide [at_offset_go, sKey] <;> omega` on `@requires(i >= 0)
    # @requires(i < n) @ensures(result <= n)` could not see either assumption,
    # `decide` had nothing to decide, and `omega` was handed a `Fin` goal it
    # has no arithmetic for.  Measured: `contract_at_offset.lean` exits 1,
    # while the same clause with `intro h; obtain ⟨h0, h1⟩ := h` in front
    # closes.  An unproved contract reported UNKNOWN is honest but is also
    # useless if the reason is that the emitter forgot two lines.
    pre_names = [f"hpre{i}" for i in range(len(pre_text))]
    if not pre_names:
        hypo = []
    elif len(pre_names) == 1:
        # Named AT the `intro`.  It was `intro hpre` followed by
        # `rename_i hpre0`, which names three binders for a two-parameter
        # theorem and is refused as "too many variable names provided" --
        # i.e. the emitted proof did not even reach the ladder.
        hypo = [f"  intro {pre_names[0]}"]
    else:
        hypo = ["  intro hpre",
                "  obtain ⟨" + ", ".join(pre_names) + "⟩ := hpre"]
    # The SPLIT prelude.  A clause over a model with an `if` in it has to be
    # case-split before `omega` can see it, and the model's own conditions are
    # the same strings `eval_eq_mojo` splits on.  This is the step whose
    # absence makes every `if n > 3:`-shaped contract UNKNOWN: `omega` on an
    # unsplit goal about a selection reports a counterexample it cannot
    # refute, which reads exactly like a false contract.
    splits = model_conditions(fn, params) if fn is not None else None
    emitted_split = splits is not None
    splits = splits or []
    hs = [f"h{i}" for i in range(len(splits))]
    by_cases = (" ".join(f"by_cases {h} : {c} <;>" for h, c in zip(hs, splits))
                if splits else "")
    simp = (", ".join(hs + pre_names + [model, "sKey",
                                        "u64_lt_iff_false_of_le",
                                        "u64_le_iff_false_of_lt"]))
    # The ladder, BUILT FROM `LADDER` rather than written out beside it.  It
    # was written out beside it, and then `LADDER` and the script disagreed --
    # `LADDER` listed four rungs and the script had three -- so `Verdict.why`
    # told a reader a contract was closed with a tactic that never ran.  That
    # is the whole failure this module exists to prevent, committed inside the
    # module that exists to prevent it.
    #
    # `first` tries each rung and takes the first that CLOSES the goal; a rung
    # that merely leaves the goal open (which is what `simp_all` and `decide`
    # do when they cannot) falls through.  So the script either proves the
    # contract or leaves the goal open for Lean to report with the theorem
    # named -- there is no rung that can swallow a failure, which is the whole
    # requirement.
    rung = _ladder_script(simp)
    lines = [f"theorem {contract.name}_contract {binders} :",
             f"    {goal} := by"] + hypo
    if not posts:
        # A contract with only preconditions: `pre → True`, which `intro`
        # alone discharges.  Emitted rather than skipped because a `@requires`
        # with no `@ensures` is a real promise and the reader is entitled to see
        # it discharged.
        lines = [f"theorem {contract.name}_contract {binders} :",
                 f"    {antecedent} → True := by",
                 "  trivial"]
        return Emission("\n".join(lines), goal, emitted_split, contract,
                        params, fn, model)
    # One bullet per postcondition, each opening with the case split the model
    # needs.  Bullets rather than one `And` split because each postcondition is
    # then separately checkable: a failure names which one broke.
    for i, _p in enumerate(post_text):
        if i:
            lines.append("  constructor")
        lines.append(f"  · {by_cases}{rung}")
    if source_note:
        spelled = ", ".join(f"`@{c.name}(...)`" if not c.is_pragma
                            else f"`# {c.name}:`" for c in contract.clauses)
        note = (f"    The ladder is `formal/contracts.py::LADDER`; a goal "
                f"it does not close is reported UNKNOWN by "
                f"`formal/contracts.py::classify`, never as a pass.\n\n")
        if not emitted_split:
            note += (
                f"    NO `by_cases` prelude: `model_conditions` could not read "
                f"this body's conditions, so the split over the model's own "
                f"`if` is absent and `omega` is handed an unsplit goal. That "
                f"is a fact about this tree's reach, not about the contract, "
                f"and `classify` will not report such a theorem PROVED.\n")
        lines.insert(0, (
            f"/-- {contract.name}'s contract, from {spelled} at "
            f"{contract.source}:{contract.line}.\n\n"
            f"    Stated over the SEMANTIC MODEL, which is derived from the "
            f"source and is what the bounded search in `formal/contracts.py` "
            f"evaluates -- not over the machine, whose per-export contract is "
            f"`lib/Contracts.lean`'s and is a separate, already-proved "
            f"chain.\n" + note + f" -/\n"))
    return Emission("\n".join(lines), goal, emitted_split, contract, params,
                    fn, model)


def model_conditions(fn, params):
    """The branch conditions of `fn`'s body, as the strings `by_cases` needs.

    Read through `formal/arm64_proof_gen.py`'s own `_collect_conds`, which is
    the ONE reader of a body condition this project has and the one
    `eval_eq_mojo`'s `by_cases` splits on.  Re-deriving it here would be a
    second rendering of a condition, and the failure that follows from two is
    measured: `eval_eq_mojo` needs the condition in the simp set so the
    hypothesis is the goal's `if` test, and a condition this module spelled
    its own way would be a hypothesis about a DIFFERENT `if` -- the goal
    unchanged, the proof failing, and the verdict UNKNOWN for a reason that
    looks exactly like a hard contract.

    Returns None when the reader raises, so the caller can report UNKNOWN
    rather than emit a theorem with NO splits -- a missing split is not a
    weaker proof, it is a proof that cannot close.
    """
    from formal import arm64_proof_gen as AP
    env = {p: p for p in params}
    try:
        return list(AP._collect_conds(fn, params[0] if params else "n", env))
    except Exception:
        return None


def unlowered_reason(contract, params, model_name=None) -> str:
    """Why a contract's clauses produced no theorem, as a sentence.

    Asked separately from `contract_theorems` because the theorem is text and
    text cannot say why it is empty.  A caller that got "" and no reason would
    have to guess between "nothing was written" and "what was written has no
    model", and those are exactly the two a reader must not confuse.
    """
    if not contract:
        return "no contract on this function"
    params = list(params)
    result_term = _result_term(model_name or f"{contract.name}_go", params)
    bad = []
    for clause in contract.requires:
        ir = _Reader(params).clause_ir(clause, params)
        if ir is None or len(_lean_of(ir)) > MAX_LEAN_CHARS:
            bad.append(clause)
    for clause in contract.ensures:
        ir = _Reader(params).clause_ir(clause, params)
        if ir is None or len(_lean_of(ir, result_term)) > MAX_LEAN_CHARS:
            bad.append(clause)
    if not bad:
        return ""
    spelled = ", ".join(
        (f"`{c.text}`" if c.is_pragma else f"`@{c.name}(...)`") for c in bad)
    return (f"{len(bad)} of {len(contract.clauses)} clause(s) has no Lean "
            f"rendering ({spelled}); the expression subset a contract may use "
            f"is literals, the parameters, `result`, `+ - * / %`, the six "
            f"comparisons, `and`/`or`/`not`, a conditional expression, and "
            f"`abs`/`min`/`max`/`clamp`")


def contract_ir(emission) -> dict:
    """The contract's clauses as IR, for `search_counterexample`.

    `{"requires": [...], "ensures": [...]}` of propositions, and the KEYS are
    the two lists rather than a flat one because the search needs to know
    which is which: it only evaluates an `@ensures` at an input that SATISFIES
    every precondition, which is the whole meaning of a conditional promise.
    """
    contract, params = emission.contract, emission.params
    return {
        "requires": [ir for ir in
                     (_Reader(params).clause_ir(c, params)
                      for c in contract.requires) if ir is not None],
        "ensures": [ir for ir in
                    (_Reader(params).clause_ir(c, params)
                     for c in contract.ensures) if ir is not None],
    }


# ── running the source, for the search's `run` ───────────────────────────────

class Unsupported(Exception):
    """A body shape the source evaluator does not model.

    Distinct from `ContractError` because it is about the FUNCTION, not the
    clause: `@requires(n > 0) @ensures(result > 0) def countdown(n): while
    ...` has two perfectly readable clauses and a body the search cannot run.
    The caller turns this into UNKNOWN with the shape named, never into a
    pass -- "the search could not run it" and "the search ran it and it held"
    are the two answers a caller must not merge.
    """


class CheckFired(Unsupported):
    """A run-time contract check FIRED -- the run-time half of a REFUTED.

    A subclass of `Unsupported` so the evaluator's own "cannot run this shape"
    machinery needs no second case, and SEPARATE from it because the two must
    not be counted alike: `Unsupported` means the search said nothing about the
    input, and a fired check means the search found a counterexample.  Counting
    a fired check as a skip is how a `--check-contracts` run that just proved
    the contract false gets reported as "nothing to say".
    """




class SourceRunner:
    """A function's body, run in Python over `UInt64` semantics.

    Why this exists rather than reusing the Lean model: the search needs a
    VALUE for `result`, and there are two candidates -- the compiled image (a
    whole build per input, and it answers about the MACHINE, which is not what
    the theorem is about) and the source body (a walk of the AST this module
    already has).  The second is chosen, and the reason the divergence risk is
    acceptable is that this is the SAME reader the model is built from for the
    node forms it covers: both read `fire_compiler`'s nodes, both take `-`/`*`
    modulo 2^64, both take a comparison as SIGNED, and `test_formal_contracts.py`
    checks them against each other over the corpus rather than asking a reader
    to.

    Every arm that is not modelled raises `Unsupported` with the node's name.
    There is no default and no `0` fallback: `formal/arm64_proof_gen.py`'s
    `_no_value_model` records what happens when a model answers `0` for a form
    it does not know -- the program builds, runs, and answers a DIFFERENT
    function's number with exit 0 -- and a search built the same way would
    report "no counterexample" about a body it never ran.
    """

    def __init__(self, fn, arity=None, fuel=SEARCH_FUEL):
        self.fn = fn
        self.fuel = fuel
        self.depth = 0
        self.arity = arity if arity is not None else len(
            getattr(fn, "params", None) or [])
        self.recursive = bool(getattr(fn, "name", None)) and fn.name in _self_calls(fn)

    # -- expressions ---------------------------------------------------
    def expr(self, node, env):
        self.fuel -= 1
        if self.fuel <= 0:
            raise Unsupported("the source evaluator ran out of its step budget")
        kind = type(node).__name__
        if kind == "IntLiteral":
            v = getattr(node, "value", None)
            if v is None:
                raw = getattr(node, "raw", None)
                try:
                    v = int(raw, 0)
                except (TypeError, ValueError):
                    raise Unsupported(f"an IntLiteral with no readable value "
                                      f"({raw!r})")
            return v & _MASK
        if kind == "BoolLiteral":
            return 1 if getattr(node, "value", False) else 0
        if kind == "IdentExpr":
            nm = getattr(node, "name", None)
            if nm not in env:
                raise Unsupported(f"the unbound name {nm!r}")
            return env[nm]
        if kind == "UnaryOp":
            op = getattr(node, "op", None)
            v = self.expr(getattr(node, "operand", None), env)
            if op == "-":
                return (-v) & _MASK
            if op == "+":
                return v
            if op == "~":
                return (~v) & _MASK
            raise Unsupported(f"the unary operator {op!r}")
        if kind == "BinaryOp":
            return self.binary(node, env)
        if kind == "TernaryExpr":
            return (self.expr(getattr(node, "then_val", None), env)
                    if self.truth(getattr(node, "condition", None), env)
                    else self.expr(getattr(node, "else_val", None), env))
        if kind == "CallExpr":
            return self.call(node, env)
        raise Unsupported(f"the expression node {kind}")

    def binary(self, node, env):
        op = getattr(node, "op", None)
        left = getattr(node, "left", None)
        right = getattr(node, "right", None)
        if op == "and":
            a = self.expr(left, env)
            return self.expr(right, env) if a != 0 else a
        if op == "or":
            a = self.expr(left, env)
            return a if a != 0 else self.expr(right, env)
        a = self.expr(left, env)
        b = self.expr(right, env)
        if op in _COMPARISONS:
            sa, sb = _signed(a), _signed(b)
            return int({"==": sa == sb, "!=": sa != sb, "<": sa < sb,
                        "<=": sa <= sb, ">": sa > sb, ">=": sa >= sb}[op])
        if op == "+":
            return (a + b) & _MASK
        if op == "-":
            return (a - b) & _MASK
        if op == "*":
            return (a * b) & _MASK
        if op == "/":
            if b == 0:
                raise Unsupported("a division by zero (the machine traps here)")
            return (a // b) & _MASK
        if op == "%":
            if b == 0:
                raise Unsupported("a zero modulus (the machine traps here)")
            return (a % b) & _MASK
        raise Unsupported(f"the binary operator {op!r}")

    def call(self, node, env):
        func = getattr(node, "func", None)
        name = func.name if isinstance(func, F.IdentExpr) else None
        args = list(getattr(node, "args", None) or [])
        if getattr(node, "kwargs", None):
            raise Unsupported(f"a call with keyword arguments ({name!r})")
        if name == CHECK_BUILTIN:
            # A check this module inserted, met again by the evaluator.  It is
            # modelled as a RAISE, not a skip: a run-time check that fires at
            # an input is the run-time half of the REFUTED verdict, and a
            # search that counted it as "could not evaluate" would throw away
            # the very finding the instrumentation exists to produce.
            #
            # The MESSAGE arguments are not evaluated.  `debug_assert` evaluates
            # them only on the failing path -- which is what
            # `formal/arm64_codegen.py::_emit_debug_assert` implements and what
            # `test_formal_debug_assert.py` pins -- and here the failing path IS
            # the raise, so there is nothing after them to keep.  That is why
            # the raised message names the check and not the source text: the
            # text was never formatted, on either side.
            if not args or not self.truth(args[0], env):
                raise CheckFired(
                    "a run-time contract check FIRED at this input")
            # A SATISFIED check has to return rather than fall through to the
            # `Unsupported` below, and its value is `0` because the only place
            # these appear is an `ExprStmt`, where the value is discarded --
            # which is what the emitter does too (`_emit_debug_assert` leaves
            # the tested word in x0 and the statement throws it away).
            return 0
        if name in ("abs", "min", "max", "clamp"):
            vals = [self.expr(a, env) for a in args]
            signed = [_signed(v) for v in vals]
            if name == "abs":
                return abs(signed[0]) & _MASK
            if name == "min":
                return min(signed) & _MASK
            if name == "max":
                return max(signed) & _MASK
            x, lo, hi = signed
            return (lo if x < lo else (hi if x > hi else x)) & _MASK
        if name == self.fn.name and self.recursive:
            if len(args) != self.arity:
                raise Unsupported(
                    f"a self-call with {len(args)} argument(s) where the "
                    f"function takes {self.arity}")
            if any(getattr(k, "name", None) for k in args):
                raise Unsupported("a self-call on a non-name argument")
            return self(*[_signed(self.expr(a, env)) for a in args])
        raise Unsupported(f"the call {name!r}")

    def truth(self, node, env):
        return self.expr(node, env) != 0

    # -- statements ---------------------------------------------------
    def body(self, stmts, env, depth=0):
        if depth > _MAX_DEPTH:
            raise Unsupported(f"a body nested deeper than {_MAX_DEPTH}")
        for st in stmts or ():
            kind = type(st).__name__
            if kind == "ReturnStmt":
                return ("return", None if getattr(st, "value", None) is None
                        else self.expr(st.value, env))
            if kind == "VarDecl":
                name = getattr(st, "name", None)
                if not isinstance(name, str):
                    raise Unsupported("a VarDecl with no name")
                env[name] = self.expr(getattr(st, "value", None), env)
            elif kind == "AssignStmt":
                lhs = getattr(st, "target", None)
                if type(lhs).__name__ != "IdentExpr":
                    raise Unsupported(f"an assignment to {type(lhs).__name__}")
                env[lhs.name] = self.expr(getattr(st, "value", None), env)
            elif kind == "IfStmt":
                env = dict(env)
                if self.truth(st.condition, env):
                    got = self.body(getattr(st, "then_body", None), env, depth + 1)
                elif getattr(st, "else_body", None):
                    got = self.body(st.else_body, env, depth + 1)
                else:
                    got = ("fall", None)
                if got[0] == "return":
                    return got
                env = got[1]
            elif kind == "WhileStmt":
                guard = _MAX_STEPS
                while self.truth(st.condition, env):
                    self.fuel -= 1
                    if self.fuel <= 0:
                        raise Unsupported("a loop that exceeded the step budget")
                    if guard <= 0:
                        raise Unsupported(f"a loop over more than {guard} steps")
                    guard -= 1
                    got = self.body(getattr(st, "body", None), env, depth + 1)
                    if got[0] == "return":
                        return got
                    env = got[1]
            elif kind == "ExprStmt":
                self.expr(getattr(st, "value", None), env)
            elif kind in ("Pass",):
                continue
            elif kind == "AssertStmt":
                if not self.truth(getattr(st, "value", None), env):
                    return ("raise", None)
            else:
                raise Unsupported(f"the statement node {kind}")
        return ("fall", env)

    def __call__(self, *words):
        """The function's result at `words`, as a word.

        Raises `Unsupported` rather than returning 0 for a body it cannot run,
        for the reason in the class docstring: a search that treats "could not
        run" as "held" is the failure this whole module is about.

        The RECURSION depth is metered, and that is not a formality: `fact` is
        a contract in this corpus (`formal/examples/fact.mojo`, `@ensures(result
        >= 0)`), it calls itself on `n - 1`, and the search's boundary inputs go
        up to `2^63`.  Unmetered, one input hangs the checker until Python's own
        `RecursionError` -- which is the wrong instrument and the wrong
        message, and lands tens of thousands of frames deep with a traceback
        that names nothing about the contract.  `RecursionError` is caught
        anyway, as the backstop for the case the counter misses.
        """
        if len(words) != self.arity:
            raise Unsupported(
                f"{self.arity} argument(s) expected, {len(words)} given")
        self.depth += 1
        if self.depth > _MAX_RECURSION:
            raise Unsupported(
                f"a recursion deeper than {_MAX_RECURSION} frames, which for "
                f"this function means the argument is too large for the search "
                f"to run it — `RecursionError` would say the same thing "
                f"tens of thousands of frames deep and name nothing about the "
                f"contract")
        try:
            return self._run(words)
        except RecursionError:
            raise Unsupported("the source evaluator hit Python's recursion "
                              "limit, which is this same depth budget reached "
                              "by another route")
        finally:
            self.depth -= 1

    def _run(self, words):
        env = {}
        for p, w in zip([q[0] for q in self.fn.params], words):
            if not isinstance(p, str):
                raise Unsupported("a parameter that is not a name")
            env[p] = w & _MASK
        got = self.body(getattr(self.fn, "body", None), env)
        if got[0] != "return":
            raise Unsupported(
                f"a body that {got[0]}s rather than returning a word; the "
                f"contract's `result` is a returned word and there is nothing "
                f"for it to be")
        return got[1]


# Bounds on the evaluator's recursion and looping, so a body it cannot finish
# raises rather than hangs.  Both are far above any function in the corpus and
# exist so a mistake in the walk is a fast failure with a name on it.
_MAX_DEPTH = 200
_MAX_STEPS = 100000

# The recursion budget, and the reason it is not `_MAX_STEPS`: a word
# argument reaches `2^63`, so even a call that decreases by one every time
# cannot be run at that input by ANY interpreter.  This number is chosen so
# every function in the corpus whose argument shrinks is runnable at every
# input the search tries, and a function that does not shrink hits it.  It is
# the boundary between "the search can answer about this" and "the search says
# nothing about this", and it is reported as the latter rather than guessed
# past.
_MAX_RECURSION = 5000


def _self_calls(fn):
    from formal.model import iter_nodes
    name = getattr(fn, "name", None)
    if not name:
        return ()
    out = set()
    for n in iter_nodes(getattr(fn, "body", None)):
        if type(n).__name__ == "CallExpr":
            f = getattr(n, "func", None)
            if isinstance(f, F.IdentExpr) and getattr(f, "name", None) == name:
                out.add(name)
    return tuple(out)


# ── the bounded search ───────────────────────────────────────────────────────

def search_counterexample(emission, run, inputs=None):
    """A concrete input that violates the contract, or None.

    `run(words)` is the model's value at those words -- a callable, supplied by
    the caller because the model belongs to the proof generator and this module
    must not own a second one.  `SourceRunner(fn)` is the default shape of
    such a callable and is what `check_source` builds.

    A `run` that raises (an `Unsupported` shape, a division by zero, an
    exhausted budget) causes that input to be SKIPPED, not counted as a pass:
    an input the search could not evaluate is one it says nothing about, and
    reporting "no counterexample found" over a skipped input would be
    reporting the skip as agreement.  When EVERY input was skipped the answer
    is `None` with `skipped` set, and `classify` reports UNKNOWN rather than
    PROVED for exactly that reason.

    The inputs are `BOUNDARY_INPUTS` plus `0 .. SEARCH_RANGE`, deduplicated in
    that order, so the sign boundary is tried before the small values and the
    counterexample a reader gets is the one a reader would guess.

    **This is not a proof and cannot become one.**  It explores a FINITE set.
    A contract that holds on every input tried and fails at 10^18 is UNKNOWN,
    not PROVED, and `classify` is the only thing that can say PROVED.
    """
    irs = contract_ir(emission)
    if not irs["requires"] and not irs["ensures"]:
        return None, 0
    params = emission.params
    tried = list(inputs if inputs is not None
                else list(BOUNDARY_INPUTS) + list(range(SEARCH_RANGE)))
    seen, ordered = set(), []
    for v in tried:
        v &= _MASK
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    fuel = [SEARCH_FUEL]
    skipped = 0
    for words in ([(v,) for v in ordered] if len(params) == 1
                  else _product(ordered, len(params))):
        env = dict(zip(params, words))
        try:
            if any(not _eval_of(r, env, fuel) for r in irs["requires"]):
                continue
            value = run(*words)
            env["result"] = value
            for e in irs["ensures"]:
                if not _eval_of(e, env, fuel):
                    return ({"inputs": tuple(words), "result": value,
                             "violates": e}, 0)
        except CheckFired as exc:
            # A fired check IS the counterexample, found by the instrumented
            # body rather than by the clause evaluation.  Reported as REFUTED
            # with the input, because that is what it is: a concrete input at
            # which the function did not keep its promise.
            return ({"inputs": tuple(words), "result": None,
                     "violates": "a run-time check fired: "
                                 f"{exc}", "fired": True}, 0)
        except ContractError:
            skipped += 1
        except Unsupported:
            skipped += 1
    return None, skipped


def _product(values, arity):
    """Every arity-tuple of `values`, in the order a reader checks them by hand."""
    if arity <= 0:
        return [()]
    out = [()]
    for _ in range(arity):
        out = [t + (v,) for t in out for v in values]
    return out


# ── the verdict ──────────────────────────────────────────────────────────────

class Verdict:
    """What checking one contract concluded, and everything that went into it.

    `status` is one of `PROVED` / `REFUTED` / `UNKNOWN` / `SKIPPED`.  `why` is
    a sentence naming the cause, `counterexample` is the witness when there is
    one, and `lean_detail` is Lean's own diagnostic when Lean ran.

    `why` is mandatory for every status including PROVED, because "proved" with
    no statement of WHAT was proved is the shape this project has been bitten by
    four times (`lib/Contracts.lean` §2): a `sorry` over a false statement is
    indistinguishable from one over a true one, and so is a green that does not
    say which theorem it is green about.
    """

    __slots__ = ("name", "status", "why", "counterexample", "lean_detail",
                 "theorem")

    def __init__(self, name, status, why, counterexample=None,
                 lean_detail="", theorem=""):
        self.name = name
        self.status = status
        self.why = why
        self.counterexample = counterexample
        self.lean_detail = lean_detail
        self.theorem = theorem

    @property
    def ok(self) -> bool:
        """Whether this verdict may be reported as a pass.

        PROVED and SKIPPED only -- and SKIPPED is here because a caller that
        asked about a specific function and found no contract deserves an
        answer, not a failure.  UNKNOWN and REFUTED are both not-ok, and they
        are SEPARATE statuses because a caller that collapses them has
        reintroduced the exact confusion this module was written to remove.
        """
        return self.status in (PROVED, SKIPPED)

    def __str__(self):
        out = f"{self.name}: {self.status.upper()} — {self.why}"
        c = self.counterexample
        if c:
            ins = ", ".join(str(v) for v in c["inputs"])
            # A `fired` counterexample came from the INSTRUMENTED body raising,
            # so there is no returned word to quote: the check fired before the
            # return, which is the whole point of checking before the return.
            got = ("the check fired" if c.get("fired")
                   else f"the model returns {_signed(c['result'])}")
            out += f" (at {ins}, {got})"
        return out

    def __repr__(self):
        return f"Verdict({self.name!r}, {self.status!r}, {self.why!r})"


def classify(emission, lean_ok=None, lean_detail="", counterexample=None,
             skipped=0):
    """One contract's verdict, from what Lean said and what the search found.

    `lean_ok` is the result of checking the emitted theorem: True, False, or
    None when Lean did not run.  The order of the decisions is the whole point
    and is not negotiable:

      * no theorem emitted -> UNKNOWN with `unlowered_reason`, or SKIPPED when
        there was no contract at all.  Never PROVED: nothing was asked.
      * a counterexample -> REFUTED, whatever Lean said.  A counterexample is
        a fact about a concrete input and outranks a tactic's opinion; and the
        case where Lean said True and the search found a witness is a BUG in
        one of the two backends, so the search's answer is the one reported and
        the disagreement is named in `why`.
      * `lean_ok` True -> PROVED, but only if the theorem was emitted WITH its
        `by_cases` prelude.  Without it the goal was unsplit, an unclosed goal
        means nothing about the contract, and reporting PROVED for one would
        make the verdict a claim about the generator's plumbing.
      * otherwise -> UNKNOWN, with Lean's own diagnostic attached, because an
        unclosed goal whose cause is unrecorded is the "never a silent pass"
        requirement unmet in the other direction.

    `lean_ok` True with no split is downgraded to UNKNOWN and says so, rather
    than raising: the caller asked a question, this is the honest answer to it,
    and a raise here would turn a fact about the tree into a crash in a tool
    that was only reporting.  `skipped` is how many of the search's inputs the
    source evaluator could not run, and it is folded into the UNKNOWN sentence
    for the same reason: "no counterexample among the inputs it could evaluate"
    is a different claim from "no counterexample".
    """
    if emission is None or not emission.lean:
        if emission is not None and not emission.contract:
            return Verdict("<none>", SKIPPED,
                           "no contract is written on this function")
        reason = (unlowered_reason(emission.contract, emission.params,
                                   emission.model) if emission
                  else "nothing to emit")
        return Verdict(emission.contract.name if emission else "<none>",
                       UNKNOWN, f"no theorem was emitted: {reason}")
    name = emission.contract.name
    if counterexample:
        agree = "" if lean_ok is not True else (
            " AND Lean accepted the theorem, which is a disagreement between "
            "the two backends and a bug in one of them — the search's answer "
            "is the one reported")
        return Verdict(name, REFUTED,
                       "a bounded search found an input satisfying every "
                       "precondition whose model's result violates a "
                       f"postcondition{agree}",
                       counterexample=counterexample,
                       lean_detail=lean_detail, theorem=emission.lean)
    skipped_note = (f"; {skipped} of the inputs were SKIPPED because the "
                    f"source evaluator could not run them, and a skipped "
                    f"input is not agreement") if skipped else ""
    if lean_ok is True:
        if not emission.split:
            return Verdict(
                name, UNKNOWN,
                "the theorem was emitted WITHOUT its `by_cases` prelude, so an "
                "unclosed goal is a fact about `model_conditions` rather than "
                "about the contract; the goal is not being reported as proved"
                + skipped_note,
                lean_detail=lean_detail, theorem=emission.lean)
        return Verdict(name, PROVED,
                       f"Lean closed `{name}_contract` with the ladder "
                       f"({' → '.join(LADDER)}) and the bounded search found "
                       f"no counterexample among "
                       f"{len(BOUNDARY_INPUTS) + SEARCH_RANGE} inputs "
                       f"(the search is a check, not part of the proof)"
                       + skipped_note,
                       lean_detail=lean_detail, theorem=emission.lean)
    return Verdict(
        name, UNKNOWN,
        "the ladder did not close the goal and the bounded search found no "
        "counterexample among the inputs it could evaluate; this is NOT a "
        "pass — the contract is undecided here" + skipped_note,
        lean_detail=lean_detail, theorem=emission.lean)


def check_source(fn, source="<source>", text=None, lean_ok=None,
                 lean_detail="", model_name=None):
    """Read one function's contract, search it, and classify it.

    The whole pipeline for a function whose body this module can run, and the
    answer to "what does this program promise, and does it keep the promise".

    `lean_ok` is passed in rather than run here because `formal/lean.py::
    run_lean` is the ONE launcher in this tree and a checker that spawned its
    own `lean` would be a second one with its own bounds -- the thing
    `formal/lean.py`'s docstring exists to prevent.  A caller with a Lean
    binary passes its verdict; a caller without one gets UNKNOWN, which is the
    honest answer and not a pass.
    """
    contract = read_contracts(fn, source, text)
    if not contract:
        return None, Verdict(contract.name, SKIPPED,
                             "no contract is written on this function")
    emission = contract_theorems(contract, _param_names(fn), model_name, fn=fn)
    runner = SourceRunner(fn)
    counterexample, skipped = (None, 0)
    try:
        counterexample, skipped = search_counterexample(emission, runner)
    except Unsupported as exc:
        return emission, Verdict(
            contract.name, UNKNOWN,
            f"the source evaluator cannot run this body ({exc}), so the "
            f"bounded search said NOTHING about the contract; that is not a "
            f"pass")
    return emission, classify(emission, lean_ok, lean_detail, counterexample,
                             skipped)


def _param_names(fn):
    names = []
    for p in (getattr(fn, "params", None) or []):
        names.append(p[0] if isinstance(p, (tuple, list)) else
                     getattr(p, "name", None))
    return [n for n in names if isinstance(n, str)] or ["n"]

# ── the runtime check ────────────────────────────────────────────────────────
#
# `--check-contracts` lowers a contract into the IMAGE, so the promise is
# checked at the run rather than only in the proof.  It answers the question the
# theorem cannot: "does THIS run, at THIS input, keep the promise", which is a
# different claim from "the model's result satisfies it for every input" and is
# the one that catches a compiler that got the model right and the bytes wrong.

# The builtin the checks lower TO.  `debug_assert` and not a new construct, for
# the reason the runtime check is four lines instead of a codegen change: both
# backends already lower it, already trap on it with the same nonzero exit
# status every other failing check leaves behind
# (`formal/arm64_codegen.py::_emit_debug_assert`), and `test_formal_debug_assert.py`
# already pins that a failing one keeps stdout comparable by not writing to it.
# A fourth lowering for "check a predicate and stop" would be a second
# implementation of something proved.
CHECK_BUILTIN = "debug_assert"

# The local an `@ensures` is checked against.  Fresh per RETURN, and fresh per
# function, because the alternative -- substituting the return expression into
# the clause textually -- evaluates the return expression TWICE, and an
# expression with a call in it is not free to evaluate twice.  The name is
# prefixed and suffixed so it cannot collide with a name the source wrote, and
# the generator asserts that rather than assuming it.
RESULT_BINDING = "__contract_result"

# How deep the rewrite descends looking for returns.  Beyond this the contract
# is reported as un-instrumentable rather than half-instrumented: a check that
# covers some of a function's returns is a check whose verdict depends on which
# path the run took, which is a worse answer than none.
MAX_INSTRUMENT_DEPTH = 60


def instrument(contract, fn):
    """`fn`'s body with its contract lowered into it, or a refusal.

    An `@requires` becomes one `debug_assert` at the top of the body; an
    `@ensures` becomes one immediately before each `return`, against a local
    holding the returned word.  A bare `return` under an `@ensures` is a
    REFUSAL rather than a skipped check: `result` is the returned word, and a
    function that returns nothing has none, so the clause is a claim about a
    value that does not exist.

    The message is a STRING LITERAL argument rather than an interpolated one,
    so the message's own construction cannot become a second expression to
    evaluate (and therefore a second thing that can fail) on the path a
    satisfied contract must never take.  `debug_assert` evaluates its messages
    only on the failing path by its own contract, and this does not weaken it.
    """
    if not contract:
        return None
    params = _param_names(fn)
    reader = _Reader(params)
    pre_irs = []
    for clause in contract.requires:
        ir = reader.clause_ir(clause, params)
        if ir is None:
            return (f"{clause.source}:{clause.line}: the precondition clause has "
                    f"no rendering, so there is nothing to check at run time "
                    f"and skipping it would report the function as checked")
        pre_irs.append(ir)
    post_irs = []
    for clause in contract.ensures:
        ir = reader.clause_ir(clause, params)
        if ir is None:
            return (f"{clause.source}:{clause.line}: the postcondition clause has "
                    f"no rendering, so there is nothing to check at run time "
                    f"and skipping it would report the function as checked")
        post_irs.append(ir)
    if RESULT_BINDING in params or RESULT_BINDING in _bound_names(fn):
        return (f"the run-time check binds the returned word to "
                f"`{RESULT_BINDING}`, and this function already uses that name "
                f"for its own value; rename one of them")
    body = list(getattr(fn, "body", None) or [])
    if post_irs:
        # `_rewrite_returns` mutates `body` IN PLACE and returns whether every
        # return was rewriteable.  It did not used to: it built a fresh list,
        # returned the flag, and the caller then assigned that EMPTY list over
        # `body` -- so an instrumented function lost its whole body and the
        # only thing left to run was the precondition check.  That is the worst
        # shape this rewrite can take, and it typechecks.
        state = {"n": 0}
        if not _rewrite_returns(body, post_irs, params, state, 0):
            return (f"a `return` with no value under an `@ensures`: the clause "
                    f"is about the returned word and a bare `return` has none, "
                    f"so the check has nothing to test")
    head = []
    for ir in pre_irs:
        head.append(_check_stmt(ir, None,
                                f"{contract.name}: precondition violated"))
    fn.body = head + body
    return None


def _check_stmt(ir, result_term, message):
    """One `debug_assert(clause, message)` as an AST statement.

    The clause comes back as IR, and the check has to be a source EXPRESSION
    for the emitter.  So the IR is printed back as a Mojo expression -- through
    a third printer, `_mojo_of`, which exists because the Lean spelling and the
    Mojo spelling of a clause differ (`∧` vs `and`, `UInt64.div` vs `/`) and
    emitting Lean into a Mojo AST would build a program nobody can compile.

    That is three printers over one reader, which is the cost of the one-reader
    discipline and is paid knowingly: three places that CAN disagree, checked
    against each other by `test_formal_contracts.py` rather than trusted.
    """
    expr = _mojo_of(ir, result_term)
    if expr is None:
        return None
    return F.ExprStmt(value=F.CallExpr(
        func=F.IdentExpr(name=CHECK_BUILTIN),
        args=[expr, F.StringLiteral(message)]))


def _mojo_of(node, result_term=None):
    """An IR node as a Mojo expression, or None when it has no spelling."""
    tag = node[0]
    if tag == _Op.LIT:
        return F.IntLiteral(value=node[1] if node[1] < (1 << 63)
                            else node[1] - (1 << 64))
    if tag == _Op.VAR:
        if node[1] == "result" and result_term is not None:
            return result_term
        return F.IdentExpr(name=node[1])
    if tag == _Op.NEG:
        inner = _mojo_of(node[1], result_term)
        return None if inner is None else F.UnaryOp(op="-", operand=inner)
    if tag == _Op.POS:
        return _mojo_of(node[1], result_term)
    if tag == _Op.INVERT:
        inner = _mojo_of(node[1], result_term)
        return None if inner is None else F.UnaryOp(op="~", operand=inner)
    if tag == _Op.ARITH:
        a = _mojo_of(node[2], result_term)
        b = _mojo_of(node[3], result_term)
        if a is None or b is None:
            return None
        return F.BinaryOp(op=node[1], left=a, right=b)
    if tag == _Op.CMP:
        a = _mojo_of(node[2], result_term)
        b = _mojo_of(node[3], result_term)
        if a is None or b is None:
            return None
        # `_Op.CMP` spells `==` as `=`, because that is what the Lean printer
        # wants.  Leaking that into a Mojo AST produced `unsupported binary
        # operator '=' on the formal arm64 path` for every `@ensures(a == b)`
        # -- found by RUNNING the instrumentation, not by reading it, which is
        # the argument for the test running it on both backends.
        return F.BinaryOp(op="==" if node[1] == "=" else node[1],
                          left=a, right=b)
    if tag in (_Op.AND, _Op.OR):
        a = _mojo_of(node[1], result_term)
        b = _mojo_of(node[2], result_term)
        if a is None or b is None:
            return None
        return F.BinaryOp(op="and" if tag == _Op.AND else "or", left=a, right=b)
    if tag == _Op.NOT:
        inner = _mojo_of(node[1], result_term)
        return None if inner is None else F.UnaryOp(op="not", operand=inner)
    if tag == _Op.TRUTHY:
        return _mojo_of(node[1], result_term)
    if tag in (_Op.ITE, _Op.SEL):
        cond = _mojo_of(node[1], result_term)
        then = _mojo_of(node[2], result_term)
        other = _mojo_of(node[3], result_term)
        if cond is None or then is None or other is None:
            return None
        return F.TernaryExpr(condition=cond, then_val=then, else_val=other)
    if tag == _Op.ABS:
        # A builtin is lowered to the SELECTION the machine can make, not to a
        # call.  `@ensures(result == abs(n))` instrumented to `abs(n)` put a
        # `BL abs` in the image, and the link audit refused it: nothing on this
        # link line defines `abs`.  The refusal is the right answer and it is
        # also the wrong experience -- the clause was readable, the CHECK was
        # expressible, and only the printer refused.  Expanding here is also
        # what makes the check agree with the Lean printer, which expands for
        # the same reason (`omega` cannot unfold a library function).
        x = _mojo_of(node[1], result_term)
        if x is None:
            return None
        return F.TernaryExpr(
            condition=F.BinaryOp(op="<", left=x,
                                 right=F.IntLiteral(value=0)),
            then_val=F.UnaryOp(op="-", operand=x),
            else_val=x)
    if tag in (_Op.MIN, _Op.MAX):
        a = _mojo_of(node[1], result_term)
        b = _mojo_of(node[2], result_term)
        if a is None or b is None:
            return None
        return F.TernaryExpr(
            condition=F.BinaryOp(op="<" if tag == _Op.MIN else ">",
                                 left=a, right=b),
            then_val=a, else_val=b)
    if tag == _Op.CLAMP:
        x = _mojo_of(node[1], result_term)
        lo = _mojo_of(node[2], result_term)
        hi = _mojo_of(node[3], result_term)
        if x is None or lo is None or hi is None:
            return None
        inner = F.TernaryExpr(
            condition=F.BinaryOp(op=">", left=x, right=hi),
            then_val=hi, else_val=x)
        return F.TernaryExpr(
            condition=F.BinaryOp(op="<", left=x, right=lo),
            then_val=lo, else_val=inner)
    return None


def _rewrite_returns(stmts, post_irs, params, state, depth):
    """Every `return E` in `stmts` becomes bind-check-return, in place.

    Returns False when a bare `return` is found under a postcondition, and
    leaves `stmts` untouched in that case so a refusal cannot leave a function
    half-rewritten -- a body with some returns checked and others not is a
    function whose contract verdict depends on control flow.
    """
    if depth > MAX_INSTRUMENT_DEPTH:
        return False
    for i, st in enumerate(stmts or ()):
        kind = type(st).__name__
        if kind == "ReturnStmt":
            value = getattr(st, "value", None)
            if value is None:
                return False
            binding = f"{RESULT_BINDING}_{state['n']}"
            state["n"] += 1
            checks = []
            for ir in post_irs:
                stmt = _check_stmt(ir, F.IdentExpr(name=binding),
                                   f"postcondition violated")
                if stmt is None:
                    return False
                checks.append(stmt)
            line = getattr(st, "line", 0) or 0
            stmts[i:i + 1] = (
                [F.VarDecl(name=binding, type_ann=None, value=value,
                           line=line)]
                + checks
                + [F.ReturnStmt(value=F.IdentExpr(name=binding), line=line)])
            return True
        if kind == "IfStmt":
            for sub in (getattr(st, "then_body", None),
                        getattr(st, "else_body", None)):
                if sub and not _rewrite_returns(sub, post_irs, params, state,
                                               depth + 1):
                    return False
        elif kind == "WhileStmt":
            if getattr(st, "body", None) and not _rewrite_returns(
                    st.body, post_irs, params, state, depth + 1):
                return False
            if getattr(st, "else_body", None) and not _rewrite_returns(
                    st.else_body, post_irs, params, state, depth + 1):
                return False
        elif kind == "ForStmt":
            if getattr(st, "body", None) and not _rewrite_returns(
                    st.body, post_irs, params, state, depth + 1):
                return False
            if getattr(st, "else_body", None) and not _rewrite_returns(
                    st.else_body, post_irs, params, state, depth + 1):
                return False
    return True


def _bound_names(fn):
    from formal.model import iter_nodes
    return {getattr(n, "name", None) for n in iter_nodes(getattr(fn, "body", None))
            if isinstance(getattr(n, "name", None), str)}


def instrument_source(path, functions, text=None):
    """Instrument every function of a unit that carries a contract.

    Returns `(instrumented, refusals)` — the names it changed and the
    `(name, sentence)` pairs it refused, and it refuses the WHOLE unit if any
    one function's contract cannot be lowered.  A unit half-instrumented is a
    unit whose run-time checking depends on which function the run entered, and
    a caller asking "were the contracts checked" cannot answer that from a
    partial result.
    """
    if text is None:
        # The pragma reader needs TEXT and a comment does not survive
        # `py_tokenize`, so this is the one place that reads the file.  A path
        # that cannot be read is not fatal: the AST is already parsed and only
        # the `# requires:` spelling is lost, so the caller's decorator clauses
        # are still checked.  It used to raise, and the traceback came out of
        # `fire.py build --formal --check-contracts` with forty frames of
        # generator internals and the real sentence -- "a source that names no
        # file" -- nowhere in it.
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError:
            text = None
    refusals = []
    instrumented = []
    for fn in functions:
        try:
            contract = read_contracts(fn, path, text)
        except ContractError as exc:
            refusals.append((getattr(fn, "name", "?"), str(exc)))
            continue
        if not contract:
            continue
        why = instrument(contract, fn)
        if why is not None:
            refusals.append((contract.name, why))
        else:
            instrumented.append(contract.name)
    if refusals:
        return [], refusals
    return instrumented, []

