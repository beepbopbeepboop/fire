"""Refusal vocabulary shared by the formal path and the compiled path.

`CodegenError`, the `case`-pattern classifier and its refusal sentences, and
`spelled` (a node as the source writes it, for a diagnostic that quotes it).

They live here and NOT in `formal/model.py` because `mojo/backend_gimple/
emit_stmts.py` (the compiled path's `match` lowering) needs exactly these and
nothing else of the 50,000-line model: importing `formal.model` from there put
the whole formal model into the self-host closure, where it has to be compiled
by the compiler it is part of. `formal/model.py` re-exports every name, so
`formal.model.CodegenError` and friends are unchanged for their other readers.
"""

import fire_compiler as F


class CodegenError(Exception):
    """A construct this formal path refuses to lower, in the user's words.

    ONE class for both backends, defined here rather than in either codegen:
    every consumer of a refusal catches it by name (build.py around the
    function pipeline and around each codegen pass, comptime_runner and
    imports.py around a nested build), and a backend that defined its own
    would be a class nobody catches — so its refusals escaped as raw
    tracebacks out of `fire.py` instead of becoming the one-line diagnostic
    they are written to be. It is a shared *decision* (what counts as a
    refusal, and that both backends raise the same thing), which is what this
    module is for."""


# ── `match`: the pattern language this path lowers, decided ONCE ─────────────
#
# `fire_compiler.py` parses a `case` pattern as an ordinary EXPRESSION
# (`_parse_match_case`: "Patterns are parsed at min_prec=1 … parsing it as a
# plain expression pattern keeps this parser simple"), so every PEP 634
# structural pattern arrives here as the expression that spells it: `case [a,
# b]:` is a `ListExpr`, `case {"k": v}:` a `DictExpr`, `case Point(x=0):` a
# `CallExpr`, `case 1 | 2:` and `case [a] as w:` both a `BinaryOp`.
#
# That is fine for a PARSER and fatal for a lowering that keeps the frontend's
# own switch-style rule — "evaluate each pattern and compare it with `==`"
# (`MatchStmt`'s docstring) — because under that rule those five shapes are not
# patterns at all, they are VALUES:
#
#     case 1 | 2:        evaluates 1 | 2 and matches the subject against 3
#     case [a, b]:       evaluates a list literal and compares it
#     case {"k": v}:     evaluates a dict literal and compares it
#     case Point(x=0):   CONSTRUCTS a Point and compares it
#     case [a] as w:     evaluates `… as w`, which is not an operator
#
# and every one of them binds nothing, which is the opposite of what this
# compiler's OWN free-variable analysis already says the first five do
# (`test_new_syntax_parsing.py::test_match`: `match_seq_pattern_binds`,
# `match_dict_pattern_binds`, `match_or_of_literals_has_no_names`,
# `match_as_binds_both_and_guard_is_a_use` — "In `match` semantics a bare name
# in a pattern is an irrefutable capture"). So the two front ends of this
# compiler already disagree about these five unless something refuses them, and
# a wrong-but-exit-0 answer is the outcome this tree treats as worse than a
# refusal.
#
# THE DECISION IS HERE AND NOT IN EITHER EMITTER because it has to be the same
# decision on both machines: `formal/build.py::_rewrite_match_statements` asks
# it once, for the whole pipeline, and lowers what it accepts — so an arm64
# image and an x86-64 image of one file cannot come to disagree about what a
# pattern means, and the Lean model each of them carries is a model of the SAME
# compares and branches (`formal/build.py` emits an `if`/`==` chain and the
# existing conditional proof applies to it unchanged).
#
# The kinds `match_pattern_kind` returns that this path will NOT lower. A tuple
# and not a set because nothing iterates it yet and a reader looking for "what
# is refused" should find the whole list in one place; the refusal sentence for
# each is in `match_pattern_refusal`, which is keyed by the same strings and
# raises `KeyError` on one that is not here — so a kind added to one and not the
# other fails at the first pattern that carries it.
MATCH_REFUSED_KINDS = (
    "or-pattern",
    "sequence pattern",
    "mapping pattern",
    "class pattern",
    # `case C():` is refused by the FORMAL path, which has no isinstance in its
    # model. The compiled path lowers it before its refusal check
    # (`mojo/backend_gimple/emit_stmts.py`), so this tuple is the formal layer's
    # refusal list, not the compiled path's.
    "class pattern (type test)",
    "as-binding",
    "enum pattern",
)


def match_pattern_kind(pattern, bound=frozenset()) -> str:
    """What one `case` pattern IS, for this path's lowering.

    Returns one of:

    * `"wildcard"` — `case _:`. Irrefutable, binds nothing.
    * `"capture"` — a bare name that is NOT already bound. Irrefutable, and it
      binds the subject (this is the one PEP 634 behaviour the switch-style
      rule keeps, because `fire_compiler.py`'s `MatchStmt` docstring keeps it
      for exactly the guard clause that needs something to test).
    * `"name"` — a bare name that IS bound: an ordinary read, compared with
      `==`. `bound` is the caller's answer to "is it bound"; see
      `formal/build.py::_match_scope_names`.
    * `"value"` — anything else that is an ordinary expression: a literal, a
      unary minus, a dotted `mod.CONST` value pattern, a subscript. Compared
      with `==`, which is CPython's own reading of a literal or dotted pattern.
    * `"class pattern (type test)"` — `case C():`, which is `isinstance(subject,
      C)`. Listed in `MATCH_REFUSED_KINDS` for the formal path; the compiled
      path lowers it (see `mojo/backend_gimple/emit_stmts.py`).
    * one of `MATCH_REFUSED_KINDS` — a PEP 634 structural pattern, refused by
      name.

    `bound` defaults to empty, so an unbound-looking name reads as a CAPTURE:
    that is the answer which refuses nothing, and the caller
    (`formal/build.py`) supplies the real binding set because only it knows what
    this unit folded, imported or declared.
    """
    if isinstance(pattern, F.IdentExpr):
        if pattern.name == "_":
            return "wildcard"
        return "capture" if pattern.name not in bound else "name"
    if isinstance(pattern, F.DottedLiteral):
        # `case .PASS:` — Mojo's enum dispatch. It is not a PEP 634 shape; it
        # is a type-relative NAME, and nothing on this path can resolve which
        # type the surrounding matched value has (`myinterpreter.py` refuses it
        # with "cannot resolve the dot-relative value '.PASS'").
        return "enum pattern"
    if isinstance(pattern, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        return "sequence pattern"
    if isinstance(pattern, F.DictExpr):
        return "mapping pattern"
    if isinstance(pattern, F.CallExpr):
        # `case C():` with no sub-pattern is a type test, isinstance(subject, C).
        # Any sub-pattern (`C(x)`, `C(x=0)`) deconstructs the subject, which
        # needs `__match_args__` resolved on the class; no path binds that yet,
        # so those stay refused.
        args = getattr(pattern, 'args', []) or []
        kwargs = getattr(pattern, 'kwargs', []) or []
        if not args and not kwargs:
            return "class pattern (type test)"
        return "class pattern"
    if isinstance(pattern, F.BinaryOp):
        if pattern.op == "as":
            return "as-binding"
        if pattern.op == "|":
            return "or-pattern"
        # Every other operator is an arithmetic expression, and the switch-style
        # rule really does compare its value — `case SHIFT + 1:` is a
        # comparison against `SHIFT + 1` in both this compiler and CPython.
        return "value"
    return "value"


def match_pattern_refusal(kind: str, spelling: str, fn_name: str,
                          line: int = 0) -> str:
    """The refusal for one PEP 634 pattern, naming the CONSTRUCT.

    A refusal that says only `MatchStmt` leaves the reader to work out which of
    the pattern languages they wrote, and it is the same sentence on both
    architectures with the machine's name swapped in — which is the pair of
    defects `FORMAL_the_two_backends_refuse_different_constructs_in_the_same_
    function.md` is about. So the message names the construct, says what the
    pattern MEANS (the part that is not obvious and is the reason it cannot be
    an expression), and says what this path would otherwise do, which for all
    five is the thing a reader must not be left to discover by running it.

    `spelling` is the source text of the pattern, read off the node, and it is
    what makes the message locatable: a reader with five `case` arms in a file
    needs to know which one.
    """
    where = f"line {line}: " if line else ""
    what = {
        "or-pattern": (
            "an or-PATTERN (`case A | B:`), which PEP 634 and this "
            "compiler's own free-variable analysis both read as \"match A or "
            "match B\" and which binds nothing. This path parses it as the "
            "`|` operator, so lowering it as an expression would compare the "
            "subject against `A | B` — for two integers that is a NUMBER "
            "(`case 1 | 2:` matches the subject 3) — and the arm would run "
            "for a value no `case` in the source names. Write the "
            "or-pattern as separate cases, or as this compiler's own "
            "comma spelling `case A, B:`, which is the one both the "
            "interpreter and this lowering read as \"A or B\""),
        "sequence pattern": (
            "a SEQUENCE PATTERN (`case [a, b]:`, `case (a, b):`, `case [a, "
            "*rest]:`), which decomposes the subject: it binds `a` and `b` and "
            "matches only a subject of exactly that length. This path parses "
            "it as a list/tuple literal, so lowering it as an expression would "
            "compare the subject against `[a, b]` — a VALUE comparison that "
            "binds nothing, matches a longer sequence of the same elements, "
            "and reads `a` and `b` as ordinary names rather than as bindings. "
            "Read the elements out before the `match` (`n = len(s)` then "
            "`if n == 2: a = s[0]; b = s[1]`)"),
        "mapping pattern": (
            "a MAPPING PATTERN (`case {\"k\": v}:`), which looks a KEY up in "
            "the subject and binds its value; it matches a mapping that has "
            "that key and is not an equality comparison against a dict "
            "literal. This path parses it as a `dict` display, so lowering it "
            "as an expression would compare the subject against "
            "`{\"k\": v}` — which binds nothing and requires the whole "
            "mapping to be equal. Read the value out before the `match` (`v = "
            "d.get(\"k\")`) and match on `v`"),
        "class pattern": (
            "a CLASS PATTERN (`case Point(x=0, y=1):`), which matches on a "
            "subject's TYPE and then deconstructs it, binding the keyword "
            "names. This path parses it as a construction, so lowering it as "
            "an expression would CALL `Point` and compare the result — a "
            "program that constructs a value to decide what to match, reads as "
            "a working feature, and answers a question about the subject with "
            "an answer about a fresh object. Dispatch on a field "
            "(`match p.x:` then `case 0:`) is the spelling that lowers here"),
        "class pattern (type test)": (
            "a CLASS TYPE TEST (`case Point():`), which is `isinstance(subject, "
            "Point)` and binds nothing. The formal model has no isinstance, so "
            "it cannot state what the test answers; lowering it as an "
            "expression would CONSTRUCT `Point()` and compare with `==`, which "
            "answers a different question. Test the type with an explicit "
            "field or value (`match p.kind:` then `case 0:`) instead"),
        "as-binding": (
            "an `as`-BINDING (`case P as w:`), which matches the whole "
            "subject and ALSO binds it to `w`. This path parses `as` as a "
            "binary operator, which is not one: `P as w` has no value to "
            "compare with `==`, so the pattern cannot be lowered at all. A "
            "bare capture is the same binding without the pattern — `case w:` "
            "binds the subject to `w` and always matches, and that is what "
            "lowers here"),
        "enum pattern": (
            "an ENUM CASE (`case .PASS:`), which names a variant of the "
            "matched value's type. The spelling is deliberately type-relative "
            "(`.PASS` rather than `Token.PASS`), and resolving it needs the "
            "type of the matched value, which is a question about the type "
            "system rather than about a pattern; nothing on this path has it "
            "(the interpreter refuses the same spelling with \"cannot resolve "
            "the dot-relative value\"). Spell the variant with its type, "
            "`case Token.PASS:`, which lowers as a value comparison"),
    }[kind]
    return (f"{where}{fn_name}: a `case` pattern is {what}. The pattern "
            f"spelled `{spelling}` is not a value this path can compare the "
            f"subject against.")


def spelled(expr) -> str:
    """`expr` as the source spells it, for a diagnostic that quotes it.

    Lives here rather than in either backend because a refusal has to be able
    to say WHICH operand it is about — `len(m)` and `len(k)` are different
    problems and a message that names neither sends the reader to look at the
    whole function — and the two backends would otherwise spell it two ways
    and a diagnostic would match on one architecture and not the other.

    Deliberately an approximation: a chain is spelled out, and anything this
    does not have a shape for is named by its node type, which is the same
    fallback `_dotted` uses for a callee it cannot flatten.
    """
    if isinstance(expr, F.StringLiteral):
        return repr(expr.value)
    if isinstance(expr, F.IdentExpr):
        return expr.name
    if isinstance(expr, F.MemberExpr):
        parts = []
        node = expr
        while isinstance(node, F.MemberExpr):
            parts.append(node.member)
            node = node.obj
        parts.append(spelled(node))
        return ".".join(reversed(parts))
    if isinstance(expr, F.CallExpr):
        callee = _flat_callee(expr)
        # **A call whose callee is a DOT — `cat().startswith("q")` — is spelled
        # through `spelled(node)` rather than named by its node type.** The
        # recursion above hands this arm a `CallExpr` for `cat()` when the chain
        # rooted here, and the fallback printed `CallExpr(...)`, so a refusal
        # about `cat().startswith("q")` quoted `CallExpr(...)` — which names no
        # construct the author wrote, and is the same complaint
        # `_emit_expr`'s own `Ellipsis` refusal makes ("a node the author never
        # wrote"). A reader sent to look for `CallExpr` finds nothing.
        #
        # The dotted callee goes through the SAME `spelled` recursion, so
        # `a.b().c` prints `a.b().c` rather than being flattened by
        # `_flat_callee`'s own rule (which would give `b` for a package path).
        func = getattr(expr, "func", None)
        if isinstance(func, F.MemberExpr):
            return f"{spelled(func)}(...)"
        # …and a call whose arguments are ALL KEYWORD is spelled with them.
        # `P(x=0, y=1)` is the shape a `case` class pattern arrives in
        # (`fire_compiler.py` parses `case Point(x=0, y=1):` as a plain call),
        # and the keywords are the whole of what the reader wrote — `(...)`
        # hides the only part that says which pattern it is. A call with
        # positional arguments keeps `(...)`, which is the shape the argument
        # arm above was written for and where the values are usually not what
        # the message is about.
        if callee and not (getattr(expr, "args", None) or []) \
                and (getattr(expr, "kwargs", None) or []):
            return "%s(%s)" % (callee, ", ".join(
                "%s=%s" % (k, spelled(v)) for k, v in expr.kwargs))
        return f"{callee}(...)" if callee else f"{type(expr).__name__}(...)"
    if isinstance(expr, F.IntLiteral):
        # The literal's VALUE, which is its spelling. Same reason as the
        # subscript arm below: a message that quotes `IntLiteral` instead of
        # `46` names the node's type rather than the thing the reader is
        # looking at.
        return str(expr.value)
    if isinstance(expr, F.SliceExpr):
        # `a[1:3]`, not `SliceExpr`. A `del a[1:3]` target PARSES as a bare
        # `SliceExpr` (the subscript is the target's own shape, not a
        # `SubscriptExpr` with a slice index), so a refusal that quotes this
        # node without spelling it named the parser's type and not the line —
        # and a stepped-slice `del` is exactly the case that needs the bounds
        # in the message.
        bounds = [getattr(expr, part, None) for part in ("start", "stop")]
        step = getattr(expr, "step", None)
        if step is not None:
            bounds.append(step)
        return (f"{spelled(expr.obj)}[{':'.join(spelled(b) for b in bounds)}]")
    if isinstance(expr, F.SubscriptExpr):
        # `p[0]`, not `SubscriptExpr`. A subscript is the one non-name shape
        # whose spelling is both short and exact, and it is the shape a byte
        # read arrives as — so the diagnostic that explains `p[0] != "."` was
        # quoting `SubscriptExpr != '.'`, which names neither the expression
        # nor the byte.
        if isinstance(expr.index, F.SliceExpr):
            return f"{spelled(expr.obj)}[...]"
        return f"{spelled(expr.obj)}[{spelled(expr.index)}]"
    if isinstance(expr, (F.TupleExpr, F.ListExpr)):
        # `(a, b)` / `[a, b]`, element by element.  Same reason as the two arms
        # above and the same defect it fixes: a message about a tuple target
        # that quotes `TupleExpr` names the parser's node type and not the line
        # the reader is looking at, and a target list is the one thing a refusal
        # about a tuple store most needs to show.
        open_c, close_c = ("(", ")") if isinstance(expr, F.TupleExpr) else ("[", "]")
        return (f"{open_c}{', '.join(spelled(e) for e in (getattr(expr, 'elements', None) or []))}"
                f"{close_c}")
    if isinstance(expr, F.DictExpr):
        # `{"k": v}`, pair by pair.  A `case` mapping pattern arrives as a dict
        # display (`fire_compiler.py` parses `case {"k": v}:` as a plain
        # expression), so the refusal that names it has to be able to quote it;
        # `DictExpr` would name the parser's node type and not the line.
        pairs = getattr(expr, "pairs", None) or []
        return "{%s}" % ", ".join(
            "%s: %s" % (spelled(pair[0]), spelled(pair[1]))
            for pair in pairs
            if isinstance(pair, (tuple, list)) and len(pair) == 2)
    if isinstance(expr, F.SetExpr):
        return "{%s}" % ", ".join(
            spelled(e) for e in (getattr(expr, "elements", None) or []))
    if isinstance(expr, F.DottedLiteral):
        # `.PASS`, not `DottedLiteral`.  Same reason as the arms above and the
        # same reader: a refusal about a `case .PASS:` that quotes the node's
        # type names nothing the author wrote — the leading dot IS the spelling
        # that makes it type-relative, so dropping it makes the message read as
        # a plain name.
        return "." + str(getattr(expr, "path", "") or "")
    if isinstance(expr, F.UnaryOp):
        # `*rest`, not `UnaryOp`.  A starred element of an assignment target is
        # a shape `__init__`'s inline refuses by name, so the refusal quotes it,
        # and `UnaryOp` tells the reader nothing they can act on.
        return f"{expr.op}{spelled(getattr(expr, 'operand', None))}"
    if isinstance(expr, F.BinaryOp):
        # `a + b`, not `BinaryOp`.  The same defect as the arm above and for the
        # same reason: an arithmetic expression is the shape a `%s` conversion is
        # most often handed by accident (`printf("[%s]", 2 + 4)`), so the
        # diagnostic that refuses it has to show the expression.
        return (f"{spelled(getattr(expr, 'left', None))} {expr.op} "
                f"{spelled(getattr(expr, 'right', None))}")
    return type(expr).__name__


def _flat_callee(call) -> str | None:
    """The dotted name a call's callee spells, or None if it is not a name.

    A module call (`os.path.join`) and a value's method (`items.append`) both
    arrive as a dotted name; the backends tell them apart by asking whether the
    receiver is a local, not by looking at the spelling."""
    func = call.func if isinstance(call, F.CallExpr) else call
    if isinstance(func, F.IdentExpr):
        return func.name
    parts = []
    node = func
    while isinstance(node, F.MemberExpr):
        parts.append(node.member)
        node = node.obj
    if parts and isinstance(node, F.IdentExpr):
        parts.append(node.name)
        return ".".join(reversed(parts))
    return None
