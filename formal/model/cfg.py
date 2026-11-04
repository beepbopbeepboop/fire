from . import *

# ── the CFG, and the "definitely stored" fixpoint over it ──────────────────
#
# `read_before_store` is a DOMINANCE question wearing a walk's clothes: the
# defect is a read that not every path to it stores, so the answer is a
# fixpoint over the function's control-flow graph rather than an ordered pass
# over its statements. Everything in this section exists to build that graph
# once, here, and for both backends to read one answer from it — the same
# reason every other layout decision in this module is shared, and the same
# reason a second CFG in an emitter would be a second opinion about which path
# runs.


class _Block:
    """A maximal run of statements with one entry and one set of successors.

    `succs` holds indices into the list `_build_cfg` returns, and `preds` is
    its transpose — built once at the end rather than maintained by hand,
    because a CFG whose forward and backward edges can disagree is worse than
    no CFG.

    `defs` is what the block's own statements STORE, and `kills` is what they
    `del`. Both are needed and they are not inverses: `del x` removes a name
    from the definitely-stored set without storing anything, which is what
    makes `del x` on one arm of a branch a read-before-store on the other.

    `seed` is the one thing a block's IN set contains for a reason other than
    its predecessors: a binding that happens BEFORE the block, for the block's
    own subtree only. A `match` case's capture pattern is the construct that
    needs it (`_match_case_binds`), and it is a separate field rather than more
    `defs` precisely because `defs` is visible to every successor and `seed` is
    not — see `_match_case_binds` for why one case's capture must not be in
    scope in another case's arm.

    `leaves` is set on a block that holds a `return`/`raise` (or a `break`/
    `continue` out of a loop ENCLOSING whatever is asking), which is the set a
    `finally` clause's predecessors are collected from — see `_leaves_early`.
    It is a property of the block's statements rather than of the block's edges
    (`succs` is empty for all of them), because the question is asked by a
    statement OUTSIDE the block: "does control ever get from here to me?".
    `breaks_at` is the `loops`-stack index such a `break`/`continue` targets,
    and `-1` for the `return`/`raise` case, which leaves unconditionally."""

    __slots__ = ("index", "stmts", "succs", "preds", "defs", "kills", "seed",
                 "leaves", "breaks_at", "intro", "false_from")

    def __init__(self, index, stmts):
        self.index = index
        self.stmts = stmts
        self.succs: list = []
        self.preds: list = []
        self.defs: set = set()
        self.kills: set = set()
        self.seed: set = set()
        self.leaves = False
        self.breaks_at = -1
        # `intro` is the CONDITION FACTS this block's entry establishes: the
        # canonical form of a test and whether it held, introduced by the one
        # branch that knows (`if c:` then `c` is true). A separate field from
        # `seed` for the same reason `seed` is one — these are facts about the
        # PATH, not names, and the fixpoint intersects them at a join rather
        # than unioning. See `_guard_facts` and `_cond_key`.
        self.intro: dict = {}
        # `false_from` is `{predecessor index: the condition whose FALSE edge
        # that is}`, and it exists because the CFG has no way to say a fact
        # about an EDGE. An `if` with no `else` reaches the join straight from
        # its own header, and on that one edge the condition is known to have
        # failed — which is what makes the guarded-names meet work, since a
        # predecessor that knows the condition failed imposes nothing. The
        # alternative was an empty block per `if` to carry the fact, and that
        # would renumber every block, which is what the graph-shape tables in
        # `test_formal_read_before_store.py` pin.
        self.false_from: dict = {}

    def __repr__(self):
        return (f"<block {self.index}: {len(self.stmts)} stmt(s), "
                f"-> {self.succs}>")


def _cfg_block_defs(stmts) -> tuple:
    """`(defs, kills)` for a straight-line run: what it stores, what it dels.

    A NAME walk and nothing else, because a straight-line run has no control
    flow in it: every statement in the block is reached whenever the block is.
    That is what makes a block the unit the fixpoint wants.

    `ExprStmt` and `Pass` are here as no-ops deliberately — they end a block
    for the reader's benefit, not the analysis's, and treating an unrecognised
    statement as a definition would put a name in `defs` that nothing stores.

    **`VarDecl` DEFINES ITS NAME ONLY WHEN IT HAS AN INITIALISER**, and the
    `getattr(s, "value", None) is not None` guard below is the whole of that
    rule. `var a: Int` with no `=` is a DECLARATION and not an assignment: it
    gives `a` a home and no value, so treating it as a definition told
    `read_before_store` that `a` was stored before any later read of it. The
    cost of that was not a wrong refusal but a MISSING one —

        def main(n: Int) -> Int:
            var a: Int
            printf("%d\\n", a)
            return 0

    builds, runs, exits 0, and prints whatever the register allocator left in
    `a`'s home (measured 2026-10-05: 1709223448 on arm64, 306062552 on x86-64),
    where CPython raises `UnboundLocalError`. It is found by
    `tools/formal_memcheck.py`'s stack/register poison as
    NONDETERMINISTIC — two plain runs of a straight-line program disagreeing is
    only ever state nobody wrote — and `formal/memcheck/local_uninitialised.mojo`
    is the row. `_definitely_stored`'s `VarDecl` arm carries the identical
    guard, because a graph and a walk that disagree about one definition is a
    refusal that appears and disappears with which one ran."""
    defs: set = set()
    kills: set = set()
    for s in (stmts or []):
        kind = type(s).__name__
        if kind in ("AssignStmt", "AugAssignStmt"):
            defs |= _store_names(getattr(s, "target", None))
        elif kind == "VarDecl":
            n = getattr(s, "name", None)
            if isinstance(n, str) and getattr(s, "value", None) is not None:
                defs.add(n)
        elif kind == "MultiAssignStmt":
            for t in (getattr(s, "targets", None) or []):
                defs |= _store_names(t)
        elif kind == "WithStmt":
            for it in (getattr(s, "items", None) or []):
                a = getattr(it, "alias", None)
                if isinstance(a, str):
                    defs.add(a)
        elif kind == "TryStmt":
            for h in (getattr(s, "handlers", None) or []):
                n = getattr(h, "name", None)
                if isinstance(n, str):
                    defs.add(n)
        elif kind == "DelStmt":
            for t in (getattr(s, "targets", None) or []):
                kills |= _store_names(t)
        elif kind in ("ComptimeVarStmt",):
            defs |= _store_names(getattr(s, "target", None))
        elif kind in ("ForStmt", "ComptimeForStmt"):
            # A loop TARGET is a definition, and it is one in the HEADER rather
            # than in the body: the body runs zero times on the first entry
            # and the target is still bound, which is what keeps
            # `for i in range(0, 100): if i > 3: break` then `return i` legal
            # (CPython's `for_range_break`, and the reason this decision is
            # not "the target is stored by the body"). `_loop_target_defs` is
            # the one reader of the exception to that, because `read_before_store`
            #'s own per-block walk asks the same question and a second answer
            # here would be a graph that disagrees with the walk over it.
            defs |= _loop_target_defs(s)
    return defs, kills




# ── CONDITION FACTS ─────────────────────────────────────────────────────────
#
# `read_before_store` answers a DOMINANCE question — is the name stored on every
# path to this read — and the graph it walks has no way to say "every path that
# reaches here passed the same test". So the shape below is refused:
#
#     is_tuple = var.startswith('(') and var.endswith(')')
#     if is_tuple:
#         var_names = gen._split_top_level_comma(inner)     # stores
#         …
#     if is_tuple:
#         emit(gen._cname(var_names[0]))                    # reads
#
# The join after the first `if` intersects the arm that stores with the arm that
# does not, so `var_names` drops out — and the second `if` is exactly where the
# name is read. The program is correct: the condition is assigned once and never
# reassigned, so every path that reaches the second test passed the first.
#
# What closes it is a fact environment alongside the stored-names one: each
# branch seeds the fact "this condition held" (or "did not"), a join intersects
# the facts, and any block that WRITES a name the condition mentions kills them.
# A read is then allowed when the name is stored outright OR when some fact that
# holds at this point implies it. See `_guard_facts` for the implication half.

# The nodes a condition may be built from for its value to be TRACKABLE: a name,
# a literal, and the operators over them. Everything else — a call, an attribute
# read, a subscript, a comprehension — can answer differently the second time it
# is evaluated, and a fact keyed on one of those would license a read CPython
# refuses, which is the one direction this analysis must never move.
_TRACKABLE_COND = (F.IdentExpr, F.BinaryOp, F.UnaryOp, F.CompareChain,
                   F.IntLiteral, F.FloatLiteral, F.StringLiteral,
                   F.BoolLiteral, F.NoneLiteral)


def _cond_key(e, depth: int = 0) -> str:
    """`e`'s canonical form, or `''` when its value is not trackable.

    A key is the condition's SHAPE, read structurally rather than off the source
    text: two syntactically identical conditions in one function have the same
    value, which is the whole mechanism — a fact keyed on one holds at the other.

    `not` is part of the key rather than a polarity, so `if c:` and `if not c:`
    are two conditions and neither implies the other. That is a real loss (an
    early-return guard written `if not ok: return` does not license a read in a
    later `if ok:` arm) and it is the safe direction: the fix is to state the
    polarity, and until someone does, a program that needs the implication is
    refused as it is today.

    `depth` bounds the recursion. The key is only ever compared with another
    key, so a deep or cyclic expression wants a coarse key rather than a hang,
    and `''` — "not trackable" — is the answer that cannot refuse anything.
    """
    if e is None or depth > 12:
        return ""
    if isinstance(e, F.IdentExpr):
        return "N:" + e.name
    if not isinstance(e, _TRACKABLE_COND):
        return ""
    if isinstance(e, F.BinaryOp):
        left = _cond_key(e.left, depth + 1)
        right = _cond_key(e.right, depth + 1)
        return "" if not left or not right else "(%s %s %s)" % (left, e.op,
                                                                right)
    if isinstance(e, F.UnaryOp):
        inner = _cond_key(e.operand, depth + 1)
        return "" if not inner else "(%s %s)" % (e.op, inner)
    if isinstance(e, F.CompareChain):
        parts: list = []
        for i, op in enumerate(e.ops):
            left = _cond_key(e.operands[i], depth + 1)
            right = _cond_key(e.operands[i + 1], depth + 1)
            if not left or not right:
                return ""
            parts.append("%s %s %s" % (left, op, right))
        return "(&%s)" % " ".join(parts)
    # A literal, by value: `if 3:` twice is the same fact twice.
    return "L:%s(%r)" % (type(e).__name__, getattr(e, "value", None))


def expr_is_repeatable(e, depth: int = 0) -> bool:
    """Whether evaluating `e` a second time yields the same value, so an emitter
    may evaluate it once for a TEST and once for the use that follows.

    **This is `_TRACKABLE_COND`'s question asked of an emitter rather than of
    the fact environment**, and it is deliberately built on that tuple instead of
    a new node list: the comment above `_TRACKABLE_COND` already says why the
    set is what it is ("a call, an attribute read, a subscript, a comprehension
    — can answer differently the second time it is evaluated"), and a second list
    would be a second answer to it that could disagree with the first.

    The one emitter that asks is the for-range loop head, and the reason is
    CPython's own rule: `for i in range(a, b)` binds `i` only when the iteration
    PRODUCES a value, so the loop's first test has to be on `start` itself and
    the store into the counter has to come after it. Testing the counter instead
    — the store first, the test second — overwrites a name that already held
    one whenever the range turns out to be empty: `i = 7; for i in range(0, 0)`
    printed `0` here and prints `7` under CPython. Two evaluations of `a` is the
    price of getting that right, so it is only paid when the answer cannot
    change; for `range(f(), 0)` the emitter keeps today's order, because
    `expr_is_repeatable` says no and a second `f()` is not free.

    Names are repeatable because nothing runs between the two evaluations — the
    emitters ask this of a value they are about to test and immediately bind —
    so a name cannot be re-bound in between. `depth` bounds the recursion for
    the same reason `_cond_key` bounds it: False, the answer that keeps the
    existing order.
    """
    if e is None or depth > 12:
        return False
    if isinstance(e, F.IdentExpr):
        return True
    if not isinstance(e, _TRACKABLE_COND):
        return False
    if isinstance(e, F.BinaryOp):
        return (expr_is_repeatable(e.left, depth + 1)
                and expr_is_repeatable(e.right, depth + 1))
    if isinstance(e, F.UnaryOp):
        return expr_is_repeatable(e.operand, depth + 1)
    if isinstance(e, F.CompareChain):
        return all(expr_is_repeatable(o, depth + 1) for o in e.operands)
    # A literal, by value: the same `0` twice is the same `0` twice.
    return True


def _cond_names(e) -> set:
    """Every name a condition READS, which is what invalidates its fact.

    `_expr_reads` with an empty `bound`, so a name mentioned anywhere in the
    expression counts — including inside a comparison's operands — and a fact
    about `a > b` dies when either `a` or `b` is written. That is the safe
    direction: killing a fact the value did not depend on only refuses more.
    """
    return set(_expr_reads(e, set()).keys())


def _facts_merge(left: dict, right) -> dict:
    """Two fact dicts unioned, or `None` when either is empty.

    Used for an `elif` arm, which knows both that the `if`'s condition FAILED
    and that its own HELD.
    """
    if not left:
        return dict(right) if right else None
    if not right:
        return dict(left)
    out = dict(left)
    out.update(right)
    return out








def _case_is_wildcard(case) -> bool:
    """Whether a `match` case is irrefutable, so the match has no fall-through.

    **This asks about a `MatchStmt` that is still in the tree, which on the
    formal build path it no longer is by the time an analysis runs.**
    `formal/build.py::_rewrite_match_statements` replaces every `match` with
    `if`/`==` chains in `_prepare_functions`, before `check_module_symbols`
    (which is where `read_before_store` is asked) runs, so this and
    `_match_case_binds` below answer for the DIRECT callers of the analysis —
    `test_formal_read_before_store.py`, and any other reader handed a parsed
    tree. They are kept rather than deleted because the analysis is a model
    function with its own contract, and a caller that hands it a `match` should
    get the right answer about one rather than a `KeyError`.

    A wildcard (`case _`) and a bare capture (`case x`) both match whatever
    reaches them, so a `match` ending in one is total and a statement after it
    is reached from every path. `case 1` / `case "s"` / `case [a, b]` are all
    refutable, and a `case` with a `guard` is refutable however its pattern
    reads — the guard is the source saying "this one might not match".

    Read off the recorded patterns rather than the source text, because the
    patterns are what the rest of the analysis reads and a text search for `_`
    would match a `_` inside a literal.

    The consequence of getting this wrong is a FALSE REFUSAL of a program that
    is correct, which is why the answer is the conservative one in the
    direction that matters: an unrecognised pattern shape is treated as
    REFUTABLE (so the fall-through edge is kept and nothing is refused), never
    as exhaustive."""
    if getattr(case, "guard", None) is not None:
        return False
    pats = getattr(case, "patterns", None) or []
    if not pats:
        return False
    for p in pats:
        if isinstance(p, F.IdentExpr):
            # `_` is the wildcard; any other bare name is a capture, which is
            # also irrefutable.
            continue
        return False
    return True


def _match_case_binds(case) -> set:
    """The names a `case`'s patterns bind, in that case's arm only.

    **This is `match` as THIS compiler implements it, and not PEP 634.**
    `fire_compiler.py`'s `MatchStmt` and `myinterpreter.py`'s
    `execute_MatchStmt` are explicit that a `case` pattern is a switch-style
    equality comparison — the patterns are evaluated as ordinary expressions —
    with ONE exception: a bare name that is not already bound in scope is a
    genuine PEP 634 capture, binds the subject, and always matches. So the
    names a pattern binds are exactly its bare non-`_` identifiers, and
    `case [a, b]` binds NOTHING: `a` and `b` there are ordinary reads of a list
    expression that is then compared with `==`, which is why this collector does
    not descend into a pattern's sub-expressions. A structural-pattern walk
    would be a second, wrong answer about what the source means.

    A capture binds BEFORE the arm's body runs, which makes it the same shape as
    a `for` target and a `with` alias: a binding that exists before the value
    the body sees. Asking that here — it was the next construct to check after
    `with` — found that the arm's body was refused for reading its own
    capture:

        def f(n):
            match n:
                case 0:
                    return 1
                case other:            # a capture: `other` is not bound yet
                    sink(other)        # refused: "other is read before …"

    **Why the names are a per-block `seed` and not more of the match head's
    `defs`.** A `defs` entry is in every successor's IN set, so putting the
    captures there would make one case's binding visible in ANOTHER case's arm
    — which would hide this real defect:

        def f(n):
            match n:
                case 0:
                    sink(a)          # `a` is bound only by the other arm
                case [a]:
                    sink(a)

    CPython raises `UnboundLocalError` in the first arm (`a` is a local of `f`
    because the capture binds it somewhere in the body), and a check that let it
    through would be the worse of the two errors. `_Block.seed` is the one
    field the intersection does not take away and only this case's own subtree
    ever sees.
    """
    binds: set = set()
    for p in (getattr(case, "patterns", None) or []):
        if isinstance(p, F.IdentExpr) and p.name != "_":
            binds.add(p.name)
    return binds


def _cfg_int_literal(e) -> object:
    """The `int` this literal node holds, or None for anything else.

    Named apart from the module's other `_int_literal_value` (line ~17500,
    which handles a boxed handle rather than a node) because two functions with
    one name and two meanings is how a call site ends up reading the wrong
    one.

    The NEGATION is folded HERE rather than by each caller, and it has to be:
    the parser does not keep `-1` as a negative literal, it is
    `UnaryOp('-', IntLiteral(1))` (`_for_step_sign`'s docstring in
    `formal/arm64_codegen.py` says so from the emitter's side, and reads the
    same shape).  `_range_is_nonempty` grew its own folding for that reason and
    said so, and the cost of the duplication was that every OTHER reader — the
    preheader's literal table above all — inherited the gap: `i = -1` bound
    nothing, so `while i:` and `if -1:` were both undecidable.  Measured, both
    ways: `if -1:` followed by a read of a name the guard stores was REFUSED by
    `read_before_store` as a false refusal, the same defect `if True:` had and
    fixed by the same rule in `_build_cfg`.  The rows are
    `test_formal_read_before_store.py`'s `if_true_guard_is_not_a_branch_ok`,
    `if_integer_literal_guard_is_not_a_branch_ok` and
    `if_negative_integer_literal_guard_is_not_a_branch_ok`, and the direction
    that keeps the fix from becoming a licence is the adjacent
    `if_false_guard_store_then_read_refused`.
    """
    if isinstance(e, F.IntLiteral):
        return e.value
    if isinstance(e, F.UnaryOp) and getattr(e, "op", None) in ("-", "+"):
        inner = _cfg_int_literal(getattr(e, "operand", None))
        if inner is None:
            return None
        return -int(inner) if e.op == "-" else int(inner)
    return None


def _range_is_nonempty(args, consts=None) -> bool:
    """Whether a `range(...)` call yields an item.

    Exactly CPython's own emptiness rule, including the step's sign — `range(5,
    0)` and `range(0, 5, -1)` are both empty and getting either wrong would
    drop an edge the program really has. Returns None ("cannot tell") for
    anything it cannot decide, so the caller keeps the zero-iteration path.

    **`consts` is the second source of evidence, and it is `_cfg_int_value`'s
    rather than a second reader of its own**: a `range` whose bound is a NAME
    decided by the preheader (`k = 0` then `range(0, k)`) is a fact about the
    program, exactly as `i = 0` then `while i < 3:` is. It is what
    (option 2 of that fix: the emptiness as a predicate, carried along every
    edge) — and what is left decided only at RUN time (a bound this path cannot
    state as a literal, a parameter among them) is handled by loop-bound flags
    in both emitters rather than guessed.

    **The step's sign needs the NEGATION folded here**, because the parser does
    not keep `-1` as a negative literal: it is `UnaryOp('-', IntLiteral(1))`
    (`_for_step_sign`'s docstring in `formal/arm64_codegen.py` says so from the
    emitter's side, and reads the same shape). So the docstring's second example
    did not hold until 2026-10-03 — `range(0, 5, -1)` answered "cannot tell"
    rather than "empty" — and every caller inherited the gap:
    `_loop_body_always_runs` kept the zero-iteration edge for a descending empty
    range (a lost precision, which only refuses), while
    `_for_target_never_binds` could not call a descending empty range empty,
    which is the half that decides whether a read of such a target is a refusal.
    Folding here rather than in a new reader is deliberate: this is the ONE
    question in the file about "what integers does this `range` have", and
    `_cfg_int_literal` stays what its own docstring says it is.

    **An ARGUMENT COUNT outside 1-3 is `None`, not a crash.**  `range()` with no
    arguments is CPython's own `TypeError` and `_cfg_int_value` has no value to
    read, so the guard is `not in (1, 2, 3)` rather than `> 3`; the old `> 3`
    guard fell through to the three-way unpack and a `for i in range():` raised
    `ValueError: not enough values to unpack` OUT of the model and into the
    build, which reports as a backend crash rather than as a refusal.
    """
    if len(args) not in (1, 2, 3):
        return None
    vals = []
    for a in args:
        # `_cfg_int_value` and not `_cfg_int_literal`: an argument the PREHEADER
        # decided (`k = 0` then `range(0, k)`) is as much a fact about the
        # program as the literal written beside it, and reading the two with
        # different readers is how the table and the call would answer the same
        # `range` differently. It is also the only reader here that knows about
        # a name, so `consts` is its argument rather than a second lookup.
        # `_cfg_int_value` and not `_cfg_int_literal`: an argument the PREHEADER
        # decided (`k = 0` then `range(0, k)`) is as much a fact about the
        # program as the literal written beside it, and reading the two with
        # different readers is how the table and the call would answer the same
        # `range` differently. It is also the only reader here that knows about
        # a name, so `consts` is its argument rather than a second lookup. The
        # `-1` spelling needs no arm of its own: `_cfg_int_literal` folds the
        # negation, which is where the parser's `UnaryOp('-', IntLiteral(1))`
        # is read by every reader at once.
        v = _cfg_int_value(a, consts)
        if v is None:
            return None
        vals.append(int(v))
    if len(vals) == 1:
        start, stop, step = 0, vals[0], 1
    elif len(vals) == 2:
        start, stop, step = vals[0], vals[1], 1
    else:
        start, stop, step = vals
    if step == 0:
        return None                       # a ValueError at run time
    return len(range(start, stop, step)) > 0


# The three answers, named once so a caller cannot answer "probably not" with a
# `False` and be indistinguishable from a decided "never".
_ALWAYS_RUNS = "always"
_NEVER_RUNS = "never"
_MAYBE_RUNS = "maybe"


def _iterable_literal_emptiness(it):
    """`'always'` / `'never'` for an iterable that is a LITERAL, else None.

    The one reader of "what does this literal yield", shared by an iterable
    written at the `for` (`for i in []`) and a NAME whose every binding on the
    path is such a literal (`xs = []` then `for i in xs`). A `range` is NOT
    this: its emptiness is a function of its arguments rather than of whether
    a written sequence has elements, so it stays `_range_is_nonempty`'s.
    """
    if isinstance(it, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        return _ALWAYS_RUNS if getattr(it, "elements", None) else _NEVER_RUNS
    if isinstance(it, F.StringLiteral):
        return _ALWAYS_RUNS if it.value else _NEVER_RUNS
    return None


def _for_emptiness(s, consts=None, seqs=None) -> str:
    """`'always'` / `'never'` / `'maybe'` — whether this `for`'s ITERABLE
    yields a value.

    **One reader for the two questions a `for` asks, and neither of them is the
    graph's.** "Did the body run at least once" is `_loop_body_always_runs`, and
    "is the target bound afterwards" is `_for_target_defs`; the second is
    `'always'` or `'never'` and the first is `'always'`, so a reader that
    answered one of them and not the other is a graph and a walk disagreeing
    about the same loop.

    It is decidable for a literal sequence (`[1, 2]`, `"ab"`), for a NAME the
    preheader decided is such a literal (`xs = []` then `for i in xs` — `seqs`,
    from `_preheader_facts`), and for a `range` whose arguments
    `_range_is_nonempty` can decide — from the literals in the call, plus
    whatever `consts` (`_preheader_facts`' integer table) has decided about a
    name. `range` is the one CALL this reads because CPython's own emptiness
    rule is a closed-form function of its three arguments. Everything else is
    `'maybe'`, which is the answer that keeps the zero-iteration edge and the
    header's definition: both are the safe direction for a loop whose emptiness
    is a run-time fact, and the read-side protection is provided by loop-bound
    flags in both emitters.
    """
    it = getattr(s, "iterable", None)
    direct = _iterable_literal_emptiness(it)
    if direct is not None:
        return direct
    if seqs and isinstance(it, F.IdentExpr):
        # A NAME the preheader decided is a SEQUENCE LITERAL, and it is the same
        # fact `for i in []` states: an empty one binds no target, so the read
        # after the loop is CPython's `UnboundLocalError` and this path refuses
        # rather than answering a leftover word. Without this arm the name was
        # not a literal at all and `'maybe'` kept the header's definition —
        # measured on both architectures, `xs = []` then `for q in xs` then
        # `printf("q=%d", q)` printed `6159200192` where CPython raises.
        resolved = _iterable_literal_emptiness(seqs.get(it.name))
        if resolved is not None:
            return resolved
    if isinstance(it, F.CallExpr) and not (getattr(it, "kwargs", None) or []):
        func = getattr(it, "func", None)
        if isinstance(func, F.IdentExpr) and func.name == "range":
            verdict = _range_is_nonempty(list(getattr(it, "args", None) or []),
                                         consts)
            if verdict is True:
                return _ALWAYS_RUNS
            if verdict is False:
                return _NEVER_RUNS
    return _MAYBE_RUNS


def _for_target_never_binds(stmt, consts=None, seqs=None) -> bool:
    """Whether this `for` provably produces NO value, so it never binds its
    target — which is CPython's rule, not an optimisation:

        i = 7
        for i in range(0, 0):
            x = 1
        print(i)          # 7

    `i` holds 7 because the iteration produced nothing, so the assignment never
    ran. Both emitters lay the loop out the same way (`_emit_loop`, per
    backend): the head test reads `range()`'s own start and the store into the
    counter is emitted AFTER it, so an empty range leaves whatever the name
    already had — which is the only layout that can produce CPython's answer.

    **And a name the loop never binds and nothing else stores is UNBOUND**, so
    the read after it is CPython's `UnboundLocalError` and this path's answer
    has to be a refusal: there is nothing in an emitted Mach-O image that means
    "this name is unbound", and a register nothing stored is the caller's
    leftover, which is the failure the "Read before store" section above exists
    to refuse. `read_before_store`'s `for` arm asks here before it counts the
    target as a definition.

    The emptiness is read through `_for_emptiness`, so it is `'never'` for a
    literal sequence, a NAME the preheader decides is such a literal (`seqs`),
    and a `range` the PREHEADER decides as well as one it writes out (`k = 0`
    then `range(0, k)`) — an emptiness this build cannot decide keeps the target
    defined, which is a real loss
    (the for-range empty-target bug)
    and the safe direction: keeping a definition can only let through a program
    whose range happened to be non-empty, where dropping it would refuse a
    program CPython runs.
    """
    return _for_emptiness(stmt, consts, seqs) == _NEVER_RUNS


def _loop_target_defs(stmt, consts=None) -> set:
    """The names a `for`'s HEADER defines — its target, unless the loop
    provably yields no value at all.

    **One reader, two callers.** `_cfg_block_defs` fills a block's `defs` with
    it and `read_before_store`'s per-block walk fills its running `live` set
    with it, and they have to agree: the fixpoint intersects the first and the
    walk reads the second, so a shape the two answered differently would be
    accepted or refused according to which one reached it first. Both pass the
    preheader's literals when they have them (`_build_cfg` does, the walk does
    not) and a name the two would decide differently is a loop whose emptiness
    depends on a value only one of them can see.
    """
    if _for_target_never_binds(stmt, consts):
        return set()
    return _store_names(getattr(stmt, "target", None))


# Not `_CMP_OPS`: generated_dispatch.py declares that bare name as a SET, and the
# self-host closure keys module globals by bare name, so a dict of the same name
# here is refused ("cannot coerce MojoDict * to MojoSet *") in this module's toplevel.
_FOLDABLE_CMP_OPS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def _cfg_int_value(e, consts=None) -> object:
    """The `int` an operand stands for, reading `consts` for a NAME.

    `_cfg_int_literal` answers "is this node a literal"; this answers "what
    integer is this operand", which is the same question plus one source of
    evidence. `consts` is `_preheader_facts`' `{name: int}` table, and a name it
    does not have is still None — the conservative answer, and the one that
    keeps the edge."""
    v = _cfg_int_literal(e)
    if v is None and consts and isinstance(e, F.IdentExpr):
        v = consts.get(e.name)
    return v


def _literal_truth(e, consts=None) -> object:
    """True/False when `e`'s value is decidable here, None when it is not.

    Only INTEGER LITERALS and the NAMES `consts` has decided, and that
    restriction is the point: an answer computed from a literal is a fact about
    the program, while an answer computed from a name would be an assumption
    about what the name holds — unless the name's every binding on the path is
    itself a literal, which is what `consts` carries and
    `_preheader_facts` establishes. Anything unrecognised — an undecided
    name, a call, a chained comparison with an undecided operand, a float — is
    None, and None is the answer that keeps the edge.

    A single `a < b` is a `BinaryOp` in this AST and only a CHAIN of two or
    more comparisons is a `CompareChain`, so both are here: reading only the
    chain is how `while 1 < 2:` — the shape a generated bound is written in —
    came out undecidable.

    `consts` is optional and its absence is exactly the old behaviour, so the
    caller that has no evidence (every caller but `_loop_body_always_runs`)
    reads the same function rather than a second copy of it.
    """
    if isinstance(e, F.BoolLiteral):
        return bool(e.value)
    # A bare INTEGER LITERAL is decided for the same reason a `BoolLiteral` is,
    # and the corpus writes the two interchangeably: `if 1:` is as ordinary a
    # spelling of "always" as `if True:`. Without this arm `while 1:` and `if
    # 1:` were undecidable, so `_loop_body_always_runs` kept the zero-iteration
    # edge for a loop that cannot take it and `_build_cfg` read a
    # constant-true `if` as a branch — one false refusal for both spellings of
    # one construct. `_cfg_int_value`, not a private read of `IntLiteral`, so
    # the `UnaryOp(-)` spelling (`if -1:`) and the preheader's table are the
    # same reader here as everywhere else.
    v = _cfg_int_value(e, consts)
    if v is not None:
        return bool(v)
    if isinstance(e, F.IdentExpr) and consts and e.name in consts:
        # A name that is DECIDED is a value, and a value is either truthy or
        # not: `while i:` with `i = 0` is a loop that never runs, and answering
        # anything else would be inventing an edge.
        return bool(consts[e.name])
    if isinstance(e, F.UnaryOp) and getattr(e, "op", None) == "not":
        inner = _literal_truth(getattr(e, "operand", None) or
                               getattr(e, "expr", None), consts)
        return None if inner is None else (not inner)
    if isinstance(e, F.BinaryOp) and getattr(e, "op", None) in _FOLDABLE_CMP_OPS:
        left = _cfg_int_value(getattr(e, "left", None), consts)
        right = _cfg_int_value(getattr(e, "right", None), consts)
        if left is None or right is None:
            return None
        return bool(_FOLDABLE_CMP_OPS[e.op](int(left), int(right)))
    if isinstance(e, F.CompareChain) and (getattr(e, "ops", None) or []):
        vals = [_cfg_int_value(o, consts)
                for o in (getattr(e, "operands", None) or [])]
        if any(v is None for v in vals):
            return None
        for op, a, b in zip(e.ops, vals, vals[1:]):
            fn = _FOLDABLE_CMP_OPS.get(op)
            if fn is None or not fn(int(a), int(b)):
                return False
        return True
    return None


def _cfg_literal_fact(e):
    """`(int, None)` / `(None, node)` for a value a preheader can carry, else None.

    The lattice value `_preheader_facts` walks, and the tuple is what keeps two
    questions from being read as each other: an integer literal (the table
    `_range_is_nonempty` and `_literal_truth` read) and a SEQUENCE/string
    literal node (the table `_for_emptiness` reads for a named iterable). One
    walk answers both because the preheader is one region and the two facts are
    established by the same intersections along the same edges.
    """
    v = _cfg_int_literal(e)
    if v is not None:
        return (int(v), None)
    if isinstance(e, (F.ListExpr, F.TupleExpr, F.SetExpr, F.StringLiteral)):
        return (None, e)
    return None


def _cfg_literal_effects(stmts, consts: dict) -> dict:
    """`consts` after a straight-line run, with each statement's own effect.

    The same statement vocabulary as `_cfg_block_defs` and the same rule about
    what a block holds — a control-flow statement is always ALONE in its block
    and its arms are separate blocks, so it has no effect here either, and the
    join intersects.

    **A binding to anything but an integer literal or a literal sequence
    REMOVES the name**, and that is the direction that matters. `i = 0` then
    `i = f()` leaves `i` undecided, so a later `while i < 3` keeps its
    zero-iteration edge; the alternative — keeping the older literal — would
    answer `True` for a program whose loop may not run at all, which is the
    wrong-answer direction this whole analysis is built to refuse.
    """
    out = dict(consts)
    for s in (stmts or []):
        kind = type(s).__name__
        if kind in ("AssignStmt", "VarDecl"):
            target = getattr(s, "target", None)
            name = getattr(s, "name", None)
            value = _cfg_literal_fact(getattr(s, "value", None))
            if value is not None:
                if kind == "AssignStmt":
                    for n in _store_names(target):
                        out[n] = value
                elif isinstance(name, str):
                    out[name] = value
                continue
            names = _store_names(target) if kind == "AssignStmt" else (
                {name} if isinstance(name, str) else set())
        elif kind in ("AugAssignStmt", "MultiAssignStmt", "DelStmt",
                      "ComptimeVarStmt", "ForStmt", "ComptimeForStmt"):
            if kind in ("MultiAssignStmt", "DelStmt"):
                names = set()
                for t in (getattr(s, "targets", None) or []):
                    names |= _store_names(t)
            else:
                names = _store_names(getattr(s, "target", None))
        elif kind == "WithStmt":
            names = {getattr(it, "alias", None)
                     for it in (getattr(s, "items", None) or [])}
        elif kind == "TryStmt":
            names = {getattr(h, "name", None)
                     for h in (getattr(s, "handlers", None) or [])}
        elif kind == "MatchStmt":
            # A `match` head binds no name of its own, and its arms'
            # CAPTURES are `None`-valued on every path, so nothing here can
            # keep a name decided that the head did not.
            names = set()
        else:
            continue
        for n in names:
            if isinstance(n, str):
                out.pop(n, None)
    return out


def _preheader_facts(blocks: list, head_index: int, entry: int,
                     entry_facts: dict = None) -> tuple:
    """`({name: int}, {name: literal-node})` decided on EVERY path into the header.

    **The second source of evidence `_loop_body_always_runs` reads.** "Did the
    body run at least once" is a question about the condition ON ENTRY, and the
    graph says nothing about values: `i = 0` then `while i < 3:` is a fact the
    preheader states and the edges cannot. So this walks the same CFG a third
    time — `head_index`'s predecessors, and everything that reaches them,
    which is every block on some path to the header and no block after it — and
    carries a "definitely this value" table along each edge.

    **`entry_facts` is the state the walk STARTS from, and it is a different
    source of evidence from the preheader's own statements.** A name the
    function never binds is a MODULE-LEVEL constant, and its value is fixed for
    the whole program (`module_entry_literal_facts` decides which names qualify
    and why), so every block's IN set begins with those facts and a local
    binding can only OVERRIDE one. Before this, the walk started empty, so a
    `for` over a module-level literal sequence (`XS = []` at file level, then
    `for q in XS`) was `'maybe'`, the header's definition of the loop target
    survived, and a read after the loop answered the caller's leftover where
    CPython raises `UnboundLocalError`. The facts are seeded at the ROOTS (a
    block with no in-region predecessor is reached only from the function
    entry), and the ordinary intersection then drops one wherever a path binds
    the name to something else, so a function that shadows the module's name
    is unaffected.

    **One walk, two tables**, because the two facts are established by the same
    intersections along the same edges and a second walk would be the same
    lattice recomputed. The integer table answers `_range_is_nonempty` (a
    `range` bound a name decided) and `_literal_truth` (a `while` condition);
    the literal-sequence table answers `_for_emptiness` for a NAMED iterable
    (`xs = []` then `for i in xs`), which is the same question `for i in []`
    asks of the literal written at the `for`.

    The lattice is a partial map, and the two directions are both deliberate:

    * a name enters a block's IN set only when EVERY predecessor's OUT set has
      it at the same value, and a predecessor with no entry for it (a path that
      does not bind it at all, or binds it from a parameter) removes it. This is
      the same intersection `_definitely_stored` does over NAMES rather than
      values, and it is why `i = 0` before one arm and `i = 5` before the other
      decides nothing;
    * it starts EMPTY and iterates up, not top-initialised, because the answer
      being computed is "is this name decided here" and an undecided name must
      not be assumed. `_definitely_stored` top-initialises because it answers
      the opposite question.

    A block's SEEDED names are dropped (`seed` is what a `match` capture puts
    there): a capture binds the subject, whose value is not a literal, and a
    seed is per-arm anyway.
    """
    region = set()
    stack = [p for p in blocks[head_index].preds] if blocks else []
    while stack:
        i = stack.pop()
        if i in region or not (0 <= i < len(blocks)) or i == head_index:
            continue
        region.add(i)
        stack.extend(blocks[i].preds)
    if not region:
        return {}, {}
    order = sorted(region)
    out: dict = {i: {} for i in order}
    # The state the walk starts from: module-level constants hold at the
    # function ENTRY, so a block with no in-region predecessor (only the entry
    # block has none) begins with them and the intersection below drops one
    # wherever a path binds the name to something else. See the docstring.
    seed_facts = dict(entry_facts or {})
    changed = True
    rounds = 0
    while changed:
        changed = False
        rounds += 1
        nxt: dict = {}
        for i in order:
            b = blocks[i]
            merged = None
            for p in b.preds:
                if p == head_index or p not in region:
                    continue
                p_out = _cfg_literal_effects(blocks[p].stmts, out[p])
                merged = dict(p_out) if merged is None else {
                    n: v for n, v in merged.items()
                    if n in p_out and p_out[n] == v}
            if merged is None:
                merged = dict(seed_facts)
            for n in b.seed:
                merged.pop(n, None)
            nxt[i] = _cfg_literal_effects(b.stmts, merged)
        for i in order:
            if nxt[i] != out[i]:
                out[i] = nxt[i]
                changed = True
        if rounds > len(order) + 2:
            break
    merged = None
    for p in blocks[head_index].preds:
        if p not in region:
            continue
        p_out = _cfg_literal_effects(blocks[p].stmts, out[p])
        merged = dict(p_out) if merged is None else {
            n: v for n, v in merged.items() if n in p_out and p_out[n] == v}
    pairs = merged or {}
    ints = {n: v[0] for n, v in pairs.items() if v[0] is not None}
    seqs = {n: v[1] for n, v in pairs.items() if v[1] is not None}
    return ints, seqs


def _loop_body_always_runs(s, consts=None, seqs=None) -> bool:
    """Whether this loop's body is guaranteed to execute at least once.

    **The one question a CFG cannot answer, and the two cases where it can.**
    "Is the join reachable without the body having run?" is a property of the
    ITERABLE (or, for a `while`, of the condition on entry), and the graph
    built from the statement tree has no such information: both the empty
    `for` and the never-true `while` look like the same edge. So this asks the
    narrow question that IS decidable — a literal-true condition, a non-empty
    literal sequence, a `range` that is not empty — and answers False for
    everything else, which keeps the zero-iteration path.

    A `for`'s half of it is `_for_emptiness`'s `'always'`, read with the same
    `consts`, so the zero-iteration edge and the header's definition of the loop
    target are decided by ONE reader of the iterable: a `range(0, k)` that
    `consts` says is non-empty loses that edge, and the same one says the
    target is bound.

    The asymmetry is the whole design: dropping that edge can only ever REMOVE
    a refusal, and only when the body provably ran, so this cannot introduce a
    wrong answer. Keeping it when the answer is merely unknown refuses a
    program that works — `while i < 3: t = 1; i = i + 1` then `print(t)` is
    exactly such a program, and `consts` is what now answers it: the preheader
    says `i = 0` and the condition says `i < 3`, so the body provably ran. The
    residual limit is a binding the preheader cannot state as a literal (`i =
    f()`, or `i` a parameter), and that one is recorded in
    `test_formal_read_before_store.py`; it is the reason the rule is here at
    all, since without it every `while True:` in the corpus would have its
    body's stores treated as non-dominating, which is a false refusal of a shape
    the language writes constantly.
    """
    kind = type(s).__name__
    if kind == "WhileStmt":
        cond = getattr(s, "condition", None)
        # Two sources of evidence, in one order and through one reader: the
        # condition's OWN literals first, which is `_literal_truth` unchanged,
        # and the preheader's constants second. The order is not cosmetic — a
        # condition the preheader makes False is still False, and answering
        # `True` from the condition's own literals alone would drop an edge the
        # program really has.
        if _literal_truth(cond) is True:
            return True
        return _literal_truth(cond, consts) is True
    if kind in ("ForStmt", "ComptimeForStmt"):
        # One reader with `_for_target_defs`'s other half: "always runs" is
        # `_for_emptiness`'s `'always'`, and the iterable shapes it reads are
        # the ones this arm used to spell out for itself.
        return _for_emptiness(s, consts, seqs) == _ALWAYS_RUNS
    return False


def _build_cfg(body, entry_facts: dict = None) -> tuple:
    """`(blocks, entry index, condition names)` for a function body.

    `condition names` is `{canonical condition: the names it reads}`, collected
    as the branches are emitted. It is returned rather than recomputed by the
    fixpoint because the fixpoint needs it to know which fact a WRITE kills,
    and re-deriving the key from the statement would be a second reader of
    "what is this condition's canonical form" — which is how the two come to
    disagree about which facts exist.

    **The builder's shape, and why it needs two pieces of state rather than
    one.** A control-flow statement's arms converge on what follows, so the
    builder has to know both "which blocks fall through to the next statement"
    (`pending`) and "which block is currently accepting straight-line
    statements" (`cur`). One list cannot be both: after an `if`, `pending` is
    the join's predecessors, and appending the next statement to `pending[-1]`
    would make the join a self-loop and lose the edge that makes the join
    reachable from the false arm. So `cur is None` after every control-flow
    statement, and the next straight-line statement opens a block linked from
    `pending` — which is the join, and is the whole join mechanism.

    That is also why an `if`/`elif`/`else` chain needs no special case for
    `elif`: an `elif` is an `if` whose "else" arm is the next `if`, so the
    chain is three statements threading one `pending` list through all three.

    `break` and `continue` are resolved against the `loops` stack rather than
    emitted as an edge to the next statement, because their target is not the
    next statement. A `break` in a loop's `else` clause is not that loop's
    `break` in Python; the `else` clause is emitted with the loop POPPED, so a
    `break` inside it attaches to the enclosing loop and an `if`-join it forms
    is the loop's real exit. Getting that wrong would invent an edge to a join
    the program cannot reach, which is the one direction that could make the
    fixpoint refuse a legal program.

    Everything unrecognised becomes a leaf statement in the current block, so
    an unknown SHAPE contributes no edge and no definition rather than a wrong
    one — the same "silence rather than a wrong answer" the statement walk
    settled for, and the direction `_definitely_stored`'s top-initialization
    then makes safe.
    """
    blocks: list = []
    cond_names: dict = {}
    # `entry_facts` arrives as `{name: literal-node}` (what
    # `module_entry_literal_facts` publishes) and the preheader walk works in
    # the `(int, node)` lattice `_cfg_literal_fact` produces, so the conversion
    # happens once here. A node the lattice cannot carry is dropped rather than
    # guessed at.
    lattice_facts: dict = {}
    for _n, _node in (entry_facts or {}).items():
        _fact = _cfg_literal_fact(_node)
        if _fact is not None:
            lattice_facts[_n] = _fact
    # `{header block index: the condition whose FALSE edge leaves it}`, consumed
    # by `open_block` as it wires each pending exit to its predecessor. See
    # `_Block.false_from`.
    false_exits: dict = {}

    def note_cond(expr) -> str:
        """The canonical form of a condition, remembering the names it reads.

        One reader for both, because the fixpoint kills a fact by asking
        "which names does this condition mention" and the two answers have to
        be about the SAME conditions — a key recorded without its names, or
        names recorded under a key the fixpoint never sees, is a fact that
        outlives the store that should have killed it.
        """
        key = _cond_key(expr)
        if key:
            cond_names.setdefault(key, _cond_names(expr))
        return key

    def new(stmts) -> _Block:
        b = _Block(len(blocks), list(stmts or []))
        b.defs, b.kills = _cfg_block_defs(b.stmts)
        blocks.append(b)
        return b

    def edge(src, dst) -> None:
        """Record `src -> dst` on BOTH lists, and it is one function because
        they have to be added together.

        `preds` used to be filled in a single pass at the end of the build, out
        of `succs`. That cannot serve `_preheader_facts`, which is called
        from INSIDE the build (a loop header's condition has to be decided
        while its own block is being emitted) and reads `preds` to find the
        blocks that reach it. Two lists maintained in two places is also how one
        of them ends up describing a different graph from the other.
        """
        if src is None or dst is None:
            return
        if not (0 <= src < len(blocks) and 0 <= dst < len(blocks)):
            return
        blocks[src].succs.append(dst)
        blocks[dst].preds.append(src)

    def open_block(stmts, pending: list, seed=None, facts=None) -> _Block:
        """Open a block for `stmts` and make every `pending` exit reach it.

        `seed` is `_Block.seed`: names this block's IN set has for a reason
        other than its predecessors, and only this block's own subtree sees
        them. It is a parameter here rather than something `run` sets
        afterwards because the FIRST block of an arm is opened from three
        different places (a statement, a control-flow statement's header, and
        `take()`), and a seed that only some of them applied would be a rule
        that fires on some `match` arms and not others — which
        `FORMAL_read_before_store_dominating_store.md` names as the specific
        way a partial rule is worse than none.

        `facts` is `_Block.intro` for the same reason and with the same
        requirement: the CONDITION FACTS this block's entry establishes, which
        only the branch that knows them can state."""
        b = new(stmts)
        if seed:
            b.seed |= set(seed)
        if facts:
            b.intro.update(facts)
        for p in pending:
            edge(p, b.index)
            if p is not None and 0 <= p < len(blocks):
                key = false_exits.get(p)
                if key:
                    b.false_from[p] = key
        return b

    def run(stmts, loops: list, pending: list, seed=None, facts=None) -> list:
        """Emit `stmts`, returning the indices that fall through to the end.

        `pending` holds the exits that reach the FIRST statement here; the
        block it opens is the first thing emitted, and the exits at the end of
        the run are what the caller joins to whatever comes next. A `break` or
        `continue` returns `[]` — control does not fall through — while adding
        itself to the loop stack, which is how the loop's own join collects it.

        `seed` names are put on the FIRST block this run opens and nowhere
        else, so the whole arm's subtree inherits them and the block after the
        statement does not. `facts` is the same contract for the CONDITION
        FACTS."""
        if not pending:
            # A run nothing can reach. It still gets a block, so an
            # unreachable region cannot leave a hole in the index space the
            # fixpoint walks.
            b = new([])
            pending = [b.index]
        cur = None
        seed_left = set(seed) if seed else None
        facts_left = dict(facts) if facts else None

        def first(stmts, pending: list) -> _Block:
            """`open_block` for the first block of this run, taking the seed
            and the facts."""
            nonlocal seed_left, facts_left
            b = open_block(stmts, pending, seed_left, facts_left)
            seed_left = None
            facts_left = None
            return b

        def take() -> _Block:
            """The block the next straight-line statement joins, opening one
            if a control-flow statement closed the previous."""
            nonlocal cur, pending
            if cur is None:
                cur = first([], pending)
                pending = [cur.index]
            return cur

        for s in (stmts or []):
            kind = type(s).__name__
            if kind == "IfStmt":
                if _literal_truth(getattr(s, "condition", None)) is True:
                    # `if <constant true>:` IS NOT A BRANCH, and reading it as
                    # one is a FALSE REFUSAL rather than a conservative one:
                    #
                    #     if True:
                    #         x = 5
                    #     print(x)
                    #
                    # builds and runs on CPython, and the header block's join
                    # intersects the then-arm's `x` with nothing — the
                    # straight-line fall-through carries none — so `x` drops out
                    # and the analysis claims CPython raises
                    # UnboundLocalError. It does not.
                    #
                    # Measured on both architectures, and found by metamorphic
                    # testing rather than by a hand-written table:
                    # `tools/formal_metamorph.py`'s `if_true` transformation
                    # wraps a statement in `if True:`, and on a 30-program
                    # `calls` sweep 8 of 30 twins came out `TWIN-DIVERGES` — one
                    # machine lowered the original and refused the twin, which
                    # needs no oracle because the twin is the same program. The
                    # regression rows are in `test_formal_read_before_store.py`
                    # (six, three each way) and `test_formal_run.py` (four, both
                    # backends).
                    #
                    # So the then-arm is emitted as the statement's ONLY
                    # continuation: no header block, no false edge, no `else`
                    # arm. The `else` arm being unreachable is the point rather
                    # than a casualty — nothing in it is a definition that
                    # dominates anything, and an emitter that lays it out anyway
                    # still never enters it, because the condition it guards is
                    # a constant.
                    #
                    # `_literal_truth` with NO `consts` is the right reader and
                    # the narrow one: it answers only from the condition's own
                    # literals, never from an assumption about a name, so this
                    # cannot license a read CPython refuses. A condition it
                    # cannot decide is `None` and takes the branch arm below
                    # unchanged.
                    pending = run(getattr(s, "then_body", None) or [], loops,
                                  pending, facts=facts)
                    cur = None
                    continue
                cond = first([s], pending)
                pending = [cond.index]
                cur = None
                # The CONDITION FACTS each arm enters with: the then-arm knows
                # the test held, an `elif` arm knows the earlier ones failed and
                # its own held, and the `else` arm (and the statement's own fall
                # through, which carries none) knows the test failed. Every arm
                # is opened from the header alone, so a fact stated here is true
                # on every path into it.
                key = note_cond(getattr(s, "condition", None))
                held = {key: True} if key else None
                failed = {key: False} if key else None
                arms = [(getattr(s, "then_body", None) or [], held)]
                for elif_cond, elif_body in (getattr(s, "elifs", None) or []):
                    ekey = note_cond(elif_cond)
                    arms.append((elif_body,
                                 _facts_merge(failed,
                                              {ekey: True} if ekey else None)))
                has_else = getattr(s, "else_body", None) is not None
                if has_else:
                    arms.append((s.else_body, failed))
                arm_exits: list = []
                for body, arm_facts in arms:
                    arm_exits += run(body, loops, [cond.index], facts=arm_facts)
                if not has_else:
                    arm_exits.append(cond.index)      # the false edge
                    if key:
                        false_exits[cond.index] = key
                pending = arm_exits
                continue
            if kind in ("WhileStmt", "ForStmt", "ComptimeForStmt"):
                head = first([s], pending)
                pending = [head.index]
                cur = None
                loop_body = getattr(s, "body", None) or []
                # A `while`'s body runs only when the condition held, and its
                # `else` clause only when the condition failed — the two facts
                # the arms can carry. A `for` has no condition to key on (its
                # iterable is evaluated once, in the header), so it carries none
                # and its body keeps whatever the enclosing path knew.
                loop_key = note_cond(getattr(s, "condition", None)) \
                    if kind == "WhileStmt" else ""
                loop_held = {loop_key: True} if loop_key else None
                loop_failed = {loop_key: False} if loop_key else None
                # `first` is the block the body opens with, which is the node
                # the back edge returns to: the condition is re-read at the
                # TOP of the body, not in the preheader, so routing the back
                # edge through `head` would put the body's definitions into the
                # preheader's OUT set — the one path that must not have them.
                # `len(blocks)` is that index because `run` creates a block for
                # the first statement of any non-empty body, whatever shape it
                # is.
                frame = {"head": head.index, "exits": [], "continues": [],
                         "first": len(blocks) if loop_body else None}
                loops.append(frame)
                body_exits = run(loop_body, loops, [head.index],
                                 facts=loop_held)
                loops.pop()
                # THE LOOP'S TARGET IS BOUND WHENEVER THE BODY IS REACHED, which
                # is a fact about the BODY's entry and not about the header's
                # definitions — so it is seeded here, where the body opens,
                # rather than left to the header's `defs`. The two answers differ
                # on the one shape that matters: a loop whose emptiness is
                # `'maybe'` binds its target on the header's exit edge as well
                # (a name read after `for i in range(0, k)` is a definition,
                # because dropping it would refuse a program CPython runs), while
                # a loop decided `'never'` binds it nowhere — and a body whose
                # head test can never pass still reads its target legally, which
                # the seed keeps right. `seed` rather than `defs` because the
                # header is a different block and this is a binding that happens
                # on the edge INTO the body; see `_Block.seed`.
                if frame["first"] is not None and kind != "WhileStmt":
                    blocks[frame["first"]].seed |= _store_names(
                        getattr(s, "target", None))
                # One preheader read for both of the loop's questions: what the
                # iterable yields on ENTRY (`_loop_body_always_runs`, which
                # decides whether the header reaches the join at all) and what it
                # binds afterwards (`_loop_target_defs`, below). Asking twice
                # would be two walks of the same graph for one answer, and they
                # have to be the same walk — a value the first can see and the
                # second cannot is a loop whose body and whose target disagree
                # about the same `range`.
                loop_consts, loop_seqs = _preheader_facts(blocks, head.index,
                                                          entry, lattice_facts)
                # The LATCH is the node the loop is in only because its body
                # ran at least once, and it is what keeps "the condition failed
                # immediately" (the `head` -> join edge below) apart from "the
                # condition failed after an iteration" (this node -> join).
                # A single header cannot express both, which is why this is a
                # separate block and not a flag on the header: without it the
                # fixpoint sees one node reached with and without the body's
                # definitions and the intersection throws the body's away for
                # every loop, `while True:` included.
                latch = new([])
                for be in body_exits:
                    edge(be, latch.index)
                for c in frame["continues"]:
                    edge(c, latch.index)
                if frame["first"] is not None:
                    edge(latch.index, frame["first"])
                # The loop's `else` clause runs when the loop finished without
                # a `break`, which is the same two paths — so it hangs off the
                # latch AND, when the body may never run, off the header.
                # Emitted with this loop POPPED, so a `break` inside it is the
                # enclosing loop's rather than this one's.
                exit_from = [latch.index]
                if not _loop_body_always_runs(s, loop_consts, loop_seqs):
                    exit_from.append(head.index)
                    # The header's exit edge IS "the condition failed", the same
                    # fact the `else` clause carries and for the same reason.
                    if loop_key:
                        false_exits.setdefault(head.index, loop_key)
                # …and on that same edge the loop binds NOTHING that only the
                # iteration could bind, when the preheader decided the iterable
                # is empty. This is the one place `_cfg_block_defs`'s own answer
                # (which sees only the literals written in the call) is refined
                # with what the path into the loop decided, and it is applied by
                # REMOVING the header's definition rather than by asking
                # `_cfg_block_defs` again: the header block already exists and
                # holds exactly the statements this loop wrote. A name the
                # preheader does not have keeps the header's definition, which
                # is the safe direction (and loop-bound flags protect the parameter case).
                if _for_target_never_binds(s, loop_consts, loop_seqs):
                    head.defs -= _store_names(getattr(s, "target", None))
                else_body = getattr(s, "else_body", None)
                if else_body:
                    pending = run(else_body, loops, exit_from,
                                  facts=loop_failed)
                else:
                    pending = exit_from
                # A `break` in the BODY also reaches the join, and that is what
                # keeps `for i in range(0, 100): if i > 3: break` then
                # `return i` legal: the loop's target is defined in the header
                # and the join is reached from the header's exit edge as well
                # as from the break. It is also why a `break` is a path to the
                # join that does NOT go through the latch: the store may be
                # after the point the break jumped from.
                pending = pending + frame["exits"]
                cur = None
                continue
            if kind == "WithStmt":
                w = first([s], pending)
                pending = run(getattr(s, "body", None) or [], loops,
                              [w.index])
                cur = None
                continue
            if kind == "TryStmt":
                t = first([s], pending)
                pending = [t.index]
                cur = None
                # `loops` depth, which decides whether a `break` inside this
                # statement LEAVES it: see the `finally` note below, where the
                # clause is entered at every point control leaves early, and a
                # `break` out of a loop INSIDE the body does not leave the
                # statement at all.
                outer_loops = len(loops)
                body_start = len(blocks)
                body_exits = run(getattr(s, "body", None) or [], loops,
                                 [t.index])
                body_end = len(blocks)
                arm_exits = list(body_exits)
                # The HANDLER ARMS ARE NOT RUN, and not as a simplification:
                # neither emitter emits them. `_emit_try` in
                # `formal/arm64_codegen.py` and `formal/x86_64_codegen.py`
                # skips the arms outright and `RaiseStmt` flushes the pending
                # `finally` clauses and then `exit(1)`s, so no edge runs from a
                # raise site into an arm and no edge runs out of one — an arm
                # contributes nothing to the image, and a graph that walks it
                # describes a program nobody is going to run.
                #
                # What that cost, measured on this very shape:
                #
                #     def probe(n):
                #         try:
                #             p = 1
                #         except ValueError:
                #             pass
                #         return p
                #
                # was REFUSED — "'p' is read at line 6 before anything in this
                # function stores it, and CPython raises UnboundLocalError for
                # that program" — with both halves false. CPython runs it and
                # `p` is 1, and the emitted image would be right: the arm's
                # `pass` stores nothing, so the path it contributed to the join
                # was a path that stored nothing and nothing else.
                #
                # The premise the old shape rested on — "a handler that stores
                # nothing is a path to the join that stores nothing, and nothing
                # in the graph says the handler will not run" — is answered by
                # the emitter: nothing CAN run it. And the direction it was
                # protecting against is now unreachable from the other side,
                # because `refuse_dropped_handler_arm` refuses an arm whose body
                # stores anything before this walk is ever asked: the only arms
                # that reach here are `pass`/`raise`/`continue`/`break` ones,
                # which store nothing on either reading. So the two halves hold
                # each other up, and each is the reason the other is safe.
                #
                # `else` runs only when the body did NOT raise and `finally`
                # runs either way, so both are ARMS of the one statement
                # rather than a chain. That is what makes a `return` inside
                # `finally` a terminating path rather than a fallthrough, and
                # a store in only one handler not a dominating store.
                #
                # …and `else` hangs off the BODY's exits, never off the
                # header. The header reaches `else` only when the body raised,
                # which is precisely the path on which `else` does NOT run, so
                # an edge from there is not a conservative extra edge — it is a
                # claim that control reaches a clause the language skips, and
                # it refused a program CPython runs:
                #
                #     try:
                #         out = build(...)
                #     except Exception:
                #         pass
                #     else:
                #         use(out)        # 'out' is always stored here
                #
                # measured on `test_struct_formal.py:603` (`out = build_module_
                # dylib(…)` in the `try`, `os.path.isfile(out)` in the `else`)
                # and in `test_formal_read_before_store.py` as
                # `try_else_clause_runs_only_when_the_body_completed`. The
                # body's exits are the only predecessors `else` really has, so
                # an `else` after a body that always returns or raises gets an
                # unreachable block — whose IN set the fixpoint initializes
                # from the top, which is the direction that cannot refuse.
                else_start = None
                else_end = None
                else_exits: list = []
                if getattr(s, "else_body", None) is not None:
                    else_start = len(blocks)
                    else_exits = run(s.else_body, loops, body_exits)
                    else_end = len(blocks)
                    arm_exits += else_exits
                # The `finally` clause runs on every way OUT of the try, so it
                # is entered from the ARMS and the statement after the whole
                # statement is reached only through it. Modelling that
                # explicitly is what makes a store in `finally` dominating
                # (`try: … finally: p = 1` then `print(p)` is legal) and a
                # store in the BODY alone not one.
                #
                # The arms themselves are the join when there is no `finally`,
                # and NOT the try's header: a header that reaches the code
                # after the try would be a path that stores nothing, which
                # reported `try: p = 1 / except: p = 2 / print(p)` — every arm
                # of it storing `p` — as a read before any store. An empty
                # `finally` falls out of the same branch correctly, because
                # `run` on an empty run returns the exits that reach it, so
                # the arms' exits and the finally's exits are the same list.
                #


                # ── WHAT ENTERS THE CLAUSE, and why it is every point control


                # LEAVES EARLY rather than "the body may have raised" ────────
                #
                # The rule this replaced was `arm_exits or [body_first]`: the
                # arms' fall-through, or — when the body has no fall-through
                # exit — the body's first block, on the reasoning that "the
                # body may have raised". That reasoning is about an EXCEPTION
                # and this backend has none. `_emit_try` in
                # `formal/arm64_codegen.py:1916` and
                # `formal/x86_64_codegen.py:1868` skip the handler arms
                # outright, and `RaiseStmt` flushes the pending finallys and
                # then `exit(1)`s (`arm64_codegen.py:1628`) — so no edge from a
                # raise site into the clause, or out of it, exists. A store LATER
                # in the body is therefore not "skipped by the path that
                # raises", and the refusal for it was resting on a path the
                # emitted image does not have.
                #
                # What the emitter DOES do is emit the clause at every point
                # the body LEAVES EARLY: `_flush_pending_finally` walks the
                # pending frames and emits their statements at the `return` /
                # `raise` / `break` / `continue` site, with `depth` 0 for a
                # return. So the clause's statements are reached from the arms'
                # fall-through AND from every block of the body and the `else`
                # that holds such a statement — which is what `_leaves_early`
                # collects, and what the second half of the rule below turns
                # into one `run` per copy.
                #
                # That is not a tidier restatement; it is a different graph,
                # and the difference is a silent wrong answer. Measured, on the
                # program CPython rejects:
                #
                #     def probe(n):
                #         try:
                #             if n > 0:
                #                 return 100
                #             v = 7
                #         finally:
                #             sink(v)
                #         return 0
                #
                # `body_exits` is non-empty here (the `if`'s false arm falls
                # through), so the old rule added no edge at all and the build
                # accepted it. arm64:
                #
                #     $ ./t1.arm64
                #     8432255232            # sink's argument: a word nobody wrote
                #     exit 100              # CPython: UnboundLocalError, exit 1
                #
                # The clause is emitted at `return 100`, before `v = 7`, so the
                # register holds whatever the caller left in it — which is the
                # worst outcome this path has, an answer that is BUILD-DEPENDENT
                # and exits 0. `test_formal_read_before_store.py`'s
                # `finally_clause_runs_at_every_point_the_body_leaves_early_`
                # refused` pins the analysis and `test_formal_run.py`'s
                # `finally_runs_where_the_body_leaves_early_not_at_its_end`
                # pins the refusal against the binary, on both architectures.
                #
                # The clause's OWN fall-through reaches the statement after the
                # try, and it is emitted only where the body falls through —
                # `_emit_try` suppresses it once a `return`/`raise` has flushed
                # the frame (`need_fallthrough = False`). So when neither the
                # body nor the `else` can fall through, `pending` is empty and
                # the code after the statement is unreachable, which
                # `_definitely_stored`'s top-initialization already answers the
                # safe way. That is the class the old rule could not express: it
                # made the clause reachable from the body's first block and so
                # judged the DEAD code after it on the state at that block,
                # which is what `“read-before-store: the shapes that still decide wrongly”`
                # measured as `try: … total = … / finally: cleanup` then
                # `print(total)` refused on seven files.
                #


                # ── AND THE CLAUSE IS EMITTED MORE THAN ONCE, which is not a


                # detail of the same rule but a second half of it ────────────
                #
                # `_flush_pending_finally` emits the clause's statements AT an
                # early exit, and `_emit_try` emits them again at the
                # fall-through — so the image holds one copy per early exit plus
                # one, and only the LAST is followed by the statement after the
                # try. ONE `run` entered from both sets says the code after the
                # try is reached with the clause's IN over ALL of them, and that
                # IN is an intersection: a name stored after an early exit is
                # missing from it, so the statement after the try was refused
                # for a name the fall-through path had stored.
                #
                # Measured on `test_gimple_runner.py:263` — `try: py = run(…);
                # if py.returncode != 0 …: return; want_out = py.stdout /
                # finally: unlink(entry)`, then `got.stdout == want_out` — which
                # is the ordinary "compute it, then compare" shape and which the
                # single-`run` form refused.
                #
                # So the clause is run once per copy: once from the falling-
                # through entries, whose exits are what the statement after the
                # try is reached from; and once from the early exits, whose exits
                # reach nothing, because each of those copies is emitted at a
                # point the function or the loop leaves.
                fin = getattr(s, "finally_body", None)
                suppressible = getattr(s, '_with_suppressible', False) or getattr(s, '_suppressible', False)
                if fin is not None:
                    early = _leaves_early(blocks, body_start, body_end,
                                           outer_loops)
                    if else_start is not None:
                        early += _leaves_early(blocks, else_start, else_end,
                                               outer_loops)
                    if not arm_exits:
                        # No copy is emitted at a fall-through, so nothing
                        # follows the statement.
                        pending = []
                    else:
                        pending = run(fin, loops, arm_exits)
                    # The early copies are emitted either way, and each of them
                    # reads the frame as it stood at that point, so a body whose
                    # every path leaves is exactly where the clause's reads have
                    # to be checked.
                    if early:
                        if suppressible:
                            # For suppressible with blocks, only exception raises
                            # can be suppressed; returns must return from function
                            raise_early = []
                            return_early = []
                            for bidx in early:
                                b = blocks[bidx]
                                # Check if it's a raise
                                is_raise = False
                                for st in getattr(b, 'stmts', []):
                                    if isinstance(st, F.RaiseStmt):
                                        is_raise = True
                                        break
                                if is_raise:
                                    raise_early.append(bidx)
                                else:
                                    return_early.append(bidx)
                            if raise_early:
                                pending = list(pending) + run(fin, loops, raise_early)
                            if return_early:
                                run(fin, loops, return_early)
                        else:
                            run(fin, loops, early)
                else:
                    pending = arm_exits
                cur = None
                continue
            if kind == "MatchStmt":
                m = first([s], pending)
                pending = [m.index]
                cur = None
                arm_exits: list = []
                exhaustive = False
                for c in (getattr(s, "cases", None) or []):
                    # The case's own captures seed THIS arm and no other: see
                    # `_match_case_binds`, which is also why they are a `seed`
                    # and not more of the match head's `defs`.
                    arm_exits += run(getattr(c, "body", None) or [], loops,
                                     [m.index], seed=_match_case_binds(c))
                    if _case_is_wildcard(c):
                        exhaustive = True
                # A `match` with no matching case FALLS THROUGH to whatever
                # follows, and that is a path to the join that stores nothing.
                # The edge is omitted only when a case is EXHAUSTIVE, which the
                # source says by ending in a wildcard (`case _`) or an
                # irrefutable capture — read off the recorded patterns, because
                # a `match` that always matches is the one case where the
                # fall-through does not exist and adding the edge anyway would
                # refuse a legal program. `FORMAL_read_before_store_dominating_store`
                # names this as the shape a partial rule gets wrong, and a
                # false refusal is the worse of the two errors here: the old
                # walk was silent on it and every program it accepted built.
                if not exhaustive:
                    arm_exits.append(m.index)
                pending = arm_exits
                continue
            if kind in ("BreakStmt", "ContinueStmt"):
                b = first([s], pending)
                if loops:
                    if kind == "BreakStmt":
                        loops[-1]["exits"].append(b.index)
                    else:
                        loops[-1]["continues"].append(b.index)
                # `leaves`, and the loop it escapes: `_flush_pending_finally`
                # is given the loop's own `fin_depth`, so a `break` out of a
                # loop INSIDE a `try` body does not flush that `try`'s clause —
                # control stays in the body and reaches it by falling through.
                # A `break` that ESCAPES the statement does flush it, and the
                # emitters do exactly that (`arm64_codegen.py:1665`,
                # `_flush_pending_finally(self._loops[-1]["fin_depth"])`). The
                # block records WHICH loop, and `_leaves_early` compares that
                # against the depth its caller was entered at.
                if loops:
                    b.leaves = True
                    b.breaks_at = len(loops) - 1
                # With no loop around it this is a syntax error CPython
                # catches, so there is no target: control does not fall
                # through, and inventing a successor would be an edge to a join
                # the program cannot reach.
                return []
            if kind in ("ReturnStmt", "RaiseStmt"):
                b = open_block([s], pending)
                # No successor: control leaves the function, and BOTH emitters
                # flush every enclosing `finally` at this point before they do
                # — so this is one of the entries into a clause that encloses
                # this statement. See the `finally` note in the `TryStmt` arm.
                b.leaves = True
                return []
            b = take()
            b.stmts.append(s)
            d, k = _cfg_block_defs([s])
            b.defs |= d
            b.kills |= k
        if cur is None and not pending:
            return []
        return pending

    # The entry block is opened FIRST, before the body is emitted, so it is
    # index 0 and the fixpoint's seed is a single place no other block can
    # reach by accident. The body is emitted WITH the entry as its pending
    # predecessor, which is the edge that makes the seed reach anything: a body
    # emitted with an empty pending list opens its own unreachable first block,
    # and every block after it then inherits the universe.
    #
    # `run`'s RETURN VALUE IS NOT EDGED FROM THE ENTRY, and that is the whole
    # reason the `+=` is not here. `run` returns the exits that fall off the
    # end of the body it was given, and every one of them is already reachable
    # from its real predecessors: the `open_block` calls inside `run` are what
    # linked them. Adding an entry edge to them as well asserts a path the
    # source does not have — from the function's first instruction straight
    # into the middle of the body — and the fixpoint pays for it, because the
    # entry's OUT is just the parameter names:
    #
    #     def f(n):
    #         p = 1
    #         while n:
    #             q = p
    #             n = n - 1
    #
    # The `while` is the body's LAST statement, so `run` returns the loop's
    # exit blocks; edgeing the entry to them makes the loop header's IN the
    # intersection of the preheader's OUT with the PARAMETER set, `p` drops
    # out of it, and `read_before_store` refuses a program CPython runs.
    #
    # Measured three times, on three corpora, by two sweeps and a bug batch
    # that found it independently — which is worth recording because a defect
    # this shape has usually turned out to be one file:
    #
    #   * `formal/hostmods/re.mojo`'s `_p_alt`, whose `while 1:` is its last
    #     statement, and the refusal it produced — "'pend' is read at line
    #     1401 before anything in this function stores it", against a
    #     `pend = entry` three lines above — took `re` out of the backend and
    #     with it every file that imports it (`work/formal4-sweep-repo-a`);
    #   * `std/collections/binary_heap.mojo`'s `_heapify_up`, whose block 0 had
    #     `succs == [1, 8]` and whose block 8 (`unsafe_write(element^)`, the
    #     read) had `preds == [0, 2, 5, 7]`, so `element` — stored in block 1 on
    #     the only path there is — was not in block 8's IN set. Same shape, and
    #     54 functions across 26 files of `std/{builtin,collections,memory,
    #     algorithm,bit}` refused with it, including all five sort helpers in
    #     `std/builtin/sort.mojo` and every method of
    #     `std/collections/{dict,list,set,deque,counter,interval,linked_list,
    #     span}.mojo` that ends in an expression statement
    #     (`work/formal4-sweep-std-a`);
    #   * five legal `struct.pack` programs in `test_struct_formal.py`, every
    #     one of them ending in `print(n)` rather than `return` — which is why
    #     the shape was invisible for so long — and every one of them refusing
    #     `n = 0; ... ; print(n)` for a `n` the source stores three lines above
    #     the read (`work/merge-bugs2`).
    #
    # `_definitely_stored` intersects over a join's predecessors, so the one
    # impossible path discarded every definition the body made. A block that
    # falls out of the end of the body needs no successor for the fixpoint
    # either: it is the last block, and `_definitely_stored` reads IN sets, not
    # exits.
    #
    # Removing the edges can only REMOVE refusals, never add one: an entry with
    # no successor makes `_definitely_stored` top-initialize everything
    # downstream, which is the safe direction for a name nothing path stores.
    # For a straight-line body it changes nothing at all — `run` returns the
    # block the entry already points at, so the `+=` was only ever a duplicate
    # edge there. And a lone entry block is the honest graph for a body with no
    # statements at all, so the empty-body case is covered by the same removal:
    # `run` returns `[entry.index]` there, and linking the entry to itself
    # stored nothing while adding a cycle the fixpoint then had to iterate.
    #
    # WHEN IT FIRED, precisely, because "the last statement is a loop" is too
    # coarse to be useful to the next reader and the coarse form was measured
    # to be wrong on a program it very obviously looks like:
    #
    #     def main() -> int:
    #         acc = 0
    #         i = 0
    #         while i < 5:
    #             acc = acc + i
    #             i = i + 1
    #         if acc > 5:
    #             return acc
    #         return 0
    #
    # The `if` IS the last statement and it reads `acc` in both arms, and the
    # old code refused nothing here — because `run` returns [] when every arm
    # of the trailing statement TERMINATES (`return`/`raise`/`break` give no
    # fall-through exit), so there was nothing to edge the entry to. The
    # condition is therefore TWO things, not one: the body's last statement is a
    # control-flow statement, AND at least one path falls OUT of it.
    # `test_formal_read_before_store.py` pins both directions — its "a body
    # whose LAST statement is an expression" section for the trailing-call half
    # of it, and its trailing-loop section for this one — because a rule stated
    # in its coarse form and measured only in that form is how the next person
    # re-derives it.
    #
    # The intersection, written out, because it is the whole mechanism and the
    # ASCII is from the same instance the sweep reported:
    #
    #     def f(a):            header.IN = entry.OUT & preheader.OUT
    #         x = a + 1                  = {params} & {…, x}     = {params}
    #         while 1:            body.IN  = header.OUT & latch.OUT
    #             if x > 3:               — `x` is in neither
    #                 return x
    #         x = x + 1
    #
    # The refusal it produced asserted that CPython raises `UnboundLocalError`
    # for the program. It does not — `formal/hostmods/re.mojo`'s `_p_alt` has
    # `pend = entry` at line 1397 and the read at 1401, and CPython is silent —
    # and that one refusal is what `sweep:repo-b` measured as
    # `codegen/dependency` on two repo files that import `re`.
    #
    # DROP THE EDGE IS STRICTLY MORE ACCURATE, not merely more permissive, and
    # the safety property is measured rather than asserted: over every function
    # of the 14 modules under `formal/hostmods/` plus `re.mojo` — 5 888 CFG
    # blocks — the orphan count (a non-entry block with no predecessor at all)
    # is **0 before and 0 after**. A block that genuinely has no predecessor is
    # unreachable, which `_definitely_stored`'s top-initialisation already
    # answers correctly (it keeps the universe and so reports no read), so this
    # change SUBTRACTS a false edge and never creates an unreachable region —
    # the only direction in which removing an intersection could lose a refusal.
    #
    # …and the soundness argument, which is the reason dropping the edge could
    # not lose a refusal: the edge could only ever REMOVE a name from a set, so
    # it could only ever invent a refusal and never miss one.  Two more shapes
    # the same refusal refused, both programs CPython runs:
    #
    #     def f(c):                      def f(rows):
    #         if c: p = 1               for i in rows:
    #         else: p = 2                   sink(i)
    #         sink(p)          # refused 'p'
    #                                    # refused 'i'
    #
    # The `for` half is the one that reached the corpus on arm64: the loop's
    # LATCH is a fall-through whenever the loop is the function's LAST
    # statement, so every read of a loop target inside the body of a trailing
    # loop was reported — `formal/arm64.py`'s `Assembler.resolve_extern` (`for
    # sym_name, … in self.extern_refs: if sym_name not in target_addrs:`)
    # among them, which put the whole of `formal/` behind a codegen gap from one
    # function.  (The `if`/`else` half is the `for`-free twin of the
    # `one_arm_store_before_a_trailing_loop_still_refused` rows in
    # `test_formal_read_before_store.py`: there a store in one arm really is not
    # dominating and the refusal is correct; it was refused here because the
    # ENTRY was also counted as a predecessor.)
    #
    # …the same edge seen from the builder.  Every edge into the body is
    # already recorded by the `open_block` inside `take`: the first straight-line
    # statement's block is opened from `pending`, which starts as
    # `[entry.index]`, so `entry -> first block` exists before `run` returns.
    # What `run` returns is the set of blocks from which control leaves the RUN
    # — `[]` for a body ending in a `return`, and the last statement's block for
    # a body that ends on a loop or a branch — so adding it made
    # `entry -> LAST block`, a path no source takes.
    #
    # A block that falls out of the FUNCTION needs no successor for the fixpoint
    # either: it is the last block, and `_definitely_stored` reads IN sets, not
    # exits.
    #
    # `preds` is NOT filled in here.  It used to be a single pass over `succs` at
    # the end of the build, which cannot serve `_preheader_facts`: that is
    # called from INSIDE the build — a loop header's condition has to be decided
    # while its own block is being emitted — and it reads `preds` to find the
    # blocks that reach it, so at that moment `preds` was empty and every
    # `_preheader_facts` answer was "the loop may not run".  `edge` now adds
    # to both lists together, so a second pass here would APPEND each
    # predecessor twice: `b.preds` would read `[head, head]` for a one-edge
    # block and the shape tests that compare a predecessor LIST — the
    # `b.preds == [head]` in `test_formal_read_before_store.py`'s
    # `check_finally_shape` among them — would fail on a graph that is correct.
    entry = new([])
    run(body, [], [entry.index])
    return blocks, entry.index, cond_names


def _leaves_early(blocks: list, start: int, end: int, outer_loops: int) -> list:
    """Indices in `blocks[start:end]` at which control leaves the statement
    that emitted them — the entries a `finally` clause is reached from.

    `start`/`end` are the block indices one `run` call added, which is how the
    `try` arm bounds the question to its OWN body or `else` (a nested
    statement's `run` lands in the same range, and its own clause consumes its
    own leaves first, so the range is read after the fact and every `leaves`
    inside it belongs to this clause too). `outer_loops` is the loop depth the
    `try` was entered at, and it is what separates the two kinds of `break`:
    one targeting a loop at or below that depth escapes the statement — and so
    flushes the clause, which is what `_flush_pending_finally(depth)` does in
    both emitters — while one targeting a loop the body opened stays inside it
    and reaches the clause by falling through.

    A `return`/`raise` is in the answer at any depth. Both are terminal for the
    FUNCTION, and both flush every enclosing clause on the way out
    (`_flush_pending_finally()` with no argument, `arm64_codegen.py:1636` and
    `x86_64_codegen.py:1447`), which is the edge that had no modelling and no
    test behind it — see the `finally` note in `_build_cfg`'s `TryStmt` arm for
    the build that measured it.
    """
    return [b.index for b in blocks[start:end]
            if b.leaves and b.breaks_at < outer_loops]


def _definitely_stored(blocks: list, entry: int, seed: set,
                       cond_names: dict = None) -> tuple:
    """`(stored_in, facts_in, guarded)` — the three domains of this question.

    **1. `stored_in`: `{block: names every path to that block stores}`.** The
    standard "definitely assigned" dataflow: a name is in a block's IN set
    when it is in EVERY predecessor's OUT set, and a block's OUT set is its IN
    set plus what it defines. Seeded at the entry with `seed` (the parameter
    names, which the CALLER stores), and iterated to a fixpoint because a loop
    makes the answer depend on itself.

    **Initialized from the TOP, not the bottom**, and that is the whole safety
    property. Every non-entry block starts as "every name is stored" and is
    narrowed; a block with no predecessor therefore keeps everything, which is
    the right answer for unreachable code (nothing can read an unstored name
    in a block nothing reaches) and the right direction in general — this
    analysis can only ever refuse a name it can PROVE no path stores, never one
    it merely failed to track.

    Intersection rather than union is what closes the bug this replaced: the
    statement walk added a branch arm's stores to the set the code after the
    branch saw, so a name stored in ONE arm looked stored to the join. Here the
    join intersects, so `if i: t = 1` then `print(t)` reports `t` — which is
    the defect — and `if c: p = 1 else: p = 2` then `print(p)` does not,
    because both arms store it. The second case is the one that says the
    analysis is a fixpoint and not a heuristic: the two shapes are the same
    graph with different arm sets.

    **2. `facts_in`: `{block: {condition key: whether it held on every path}}`.**
    The same lattice one level up: a fact survives a join only when EVERY
    predecessor agrees, a branch introduces its own (and an `elif` arm carries
    both its own and the ones it failed), and a block that WRITES a name its
    condition mentions kills it — `is_tuple = f()` kills the fact about
    `is_tuple`, which is the whole invalidation rule and the reason
    `_cond_names` exists. A fact the inherited set and the block's own `intro`
    DISAGREE about is dropped rather than either value winning, because the
    disagreement is a path the analysis cannot describe (an `if c:` inside the
    `else:` of another `if c:`) and a fact there would be a claim about
    unreachable code.

    **3. `guarded_in` / `guarded_out`: `{block: {condition key: names stored
    WHENEVER that condition held}}`** — the implication the first two cannot
    express, and the one that closes the correlated-condition shape:

        is_tuple = var.startswith('(') and var.endswith(')')
        if is_tuple:
            var_names = gen._split_top_level_comma(inner)     # stores
        if is_tuple:
            emit(gen._cname(var_names[0]))                    # reads

    At the join after the first `if`, `var_names` is in
    `guarded_out[join][is_tuple]` and not in `stored_in[join]`: the arm that
    stores it knows the condition held, and the arm that does not knows it did
    NOT — so the implication is vacuously satisfied on the second path and
    holds on the first. The second `if` then re-establishes the fact, and the
    read is licensed. **Skipping the vacuous predecessor is the whole
    mechanism**: counting it as a claim intersects the implication away at the
    join and leaves the analysis exactly where it was, which is what the first
    version of this did.

    The claim is computed at a block's EXIT and read at its ENTRY, and the two
    are separate because a read consults the entry form: the block's own
    definitions run after any statement above them, so a claim carrying them
    would license a read of a name the block stores LATER. And it is
    initialised from the TOP and narrowed, like the other two, because a
    narrowing iteration over a loop-carried claim is the only way to get one:
    the loop body's paths all pass the header that established the fact, which
    no single forward pass sees.

    All three run in ONE loop because they narrow together and the third needs
    the first two: a separate function per domain would mean passing the
    universe and the fact map between them for nothing.
    """
    everything = set()
    for b in blocks:
        everything |= b.defs
        # A seeded name is in a block's IN set with no definition anywhere that
        # would have put it there (`_Block.seed`), so the top-initialization
        # has to know it exists or the first narrowing round drops it again.
        everything |= b.seed
    for node in iter_nodes([b.stmts for b in blocks]):
        everything |= set(_expr_reads(node, set()).keys())
    universe = everything | set(seed)
    out: dict = {b.index: (set(seed) if b.index == entry else set(universe))
                 for b in blocks}
    keys = sorted(cond_names or {})
    facts: dict = {b.index: {} for b in blocks}
    for b in blocks:
        facts[b.index] = {k: v for k, v in b.intro.items()}
    # `guarded_out` is the working array and `guarded_in` is what the caller
    # reads: a name is available at a READ POINT only if the implication held
    # when the block was ENTERED, so the block's own definitions — which run
    # after any statement above them — must not be in the value a read consults.
    # **This domain is initialised from the BOTTOM and grows, which is the
    # opposite choice from the stored-names domain above and is not a
    # preference.** A claim is a set of names the analysis PROVES are stored
    # whenever the condition held, so "no names" is the safe starting point and
    # "every name" is not: seeding it with the universe had the header of the
    # first `if` imply every name, which propagated into the join and made the
    # mechanism a no-op. Growing means the transfer must be monotone upwards —
    # a block's claim is the meet over its predecessors' claims plus its own
    # definitions, and both only gain — which is what makes the loop-carried
    # claim converge instead of oscillating.
    #
    # The cost of the bottom is that the meet cannot tell "this predecessor
    # proved nothing" from "this predecessor proved nothing on any path", and it
    # treats both as the latter, which is the direction that refuses more.
    guarded_out: dict = {b.index: {k: frozenset() for k in keys}
                         for b in blocks}
    guarded_in: dict = {b.index: {k: frozenset() for k in keys}
                        for b in blocks}
    changed = True
    rounds = 0
    while changed:
        changed = False
        rounds += 1
        for b in blocks:
            if not b.preds and b.index != entry:
                continue
            merged = None
            merged_facts = None
            for p in b.preds:
                # `(IN | defs) - kills`, and the order is the point: inside one
                # block the statements run in order, so a `del` after a store
                # (`p = 1` then `del p`) leaves the name unbound. Applying the
                # kill BEFORE the defs would put `p` back and miss exactly the
                # case `kills` exists for.
                p_out = (out[p] | blocks[p].defs) - blocks[p].kills
                merged = set(p_out) if merged is None else (merged & p_out)
                pf = facts[p]
                # The same first-round back-edge skip as the claim below, and
                # for the same reason: a fact is true here only if every path
                # says so, and a loop's own body cannot say so until the header
                # that enters it has — so counting the un-computed back edge
                # drops the fact at the body and every path round the loop loses
                # it. A `while`'s body really is only reachable when the
                # condition held.
                if rounds == 1 and p > b.index:
                    continue
                # `pf.get(k) is v` and NOT `pf.get(k, v) is v`: a predecessor
                # that says nothing about the condition DISAGREES about it being
                # true on every path, because a path that reached here without
                # passing any test of it is one where it may be false. The
                # default made those agree, and a join after a `break` out of
                # one arm of a loop — whose other predecessor is the loop
                # header, which never tested anything — came out believing the
                # body's fact and accepted `return p` where CPython raises.
                merged_facts = (
                    dict(pf) if merged_facts is None
                    else {k: v for k, v in merged_facts.items()
                          if pf.get(k) is v})
            if merged is None:
                # The entry block has no predecessors: its IN set is the seed
                # and its facts are whatever it introduces.
                merged = set(seed)
                merged_facts = {}
            else:
                # A `seed` is not reachable from any predecessor and the
                # intersection cannot restore it, so it is added AFTER it —
                # which is the whole reason it is a field of its own rather
                # than a def of this block (that would leak into successors
                # outside the arm). See `_match_case_binds`.
                merged |= b.seed
            for k, v in b.intro.items():
                if merged_facts.get(k, v) is not v:
                    del merged_facts[k]       # a contradiction is no fact
                else:
                    merged_facts[k] = v
            # A write to any name the condition mentions kills that fact.
            written_here = b.defs | b.kills
            if written_here and merged_facts:
                merged_facts = {
                    k: v for k, v in merged_facts.items()
                    if not ((cond_names or {}).get(k) or set()) & written_here}
            if merged != out[b.index]:
                out[b.index] = merged
                changed = True
            if merged_facts != facts[b.index]:
                facts[b.index] = merged_facts
                changed = True
            # The implication, per condition: "if this condition held, these names are
            # stored". It is computed for EVERY block, not only the ones whose
            # facts say the condition holds, because the block between the two
            # tests does not know the condition's value and is exactly where the
            # claim has to survive:
            #
            #     if c:            # the arm stores, and knows c held
            #         t = 1
            #     if c:            # THIS header does not know c's value
            #         print(t)     # …and this arm does, and reads
            #
            # `guarded_out[b][K]` is the claim at b's EXIT and `guarded_in[b][K]`
            # the claim at its ENTRY, and they are separate because a read
            # consults the entry form: the block's own definitions run after any
            # statement above them, so a claim carrying them would license a
            # read of a name the block stores LATER.
            #
            # The meet skips a predecessor that reaches this block only by the
            # condition having FAILED — it is vacuous there, and `false_from` is
            # how an edge says so when the predecessor itself does not know.
            # **Skipping it is the whole mechanism**: with the false edge
            # counted as a claim, the join after the first `if` intersects a
            # name only the true arm stores against a predecessor that never
            # stored it, and the claim is gone before the second `if` can use it.
            merged_in: dict = {}
            merged_out: dict = {}
            for k in keys:
                # A block that WRITES a name the condition mentions drops the
                # claim: the condition's own value moved, so an implication
                # carried from an EARLIER test of it says nothing about here —
                # the fact is dead and the claim that rode on it dies with it.
                # `is_tuple = f()` between two `if is_tuple:` arms is the
                # shape, and dropping only the fact would leave the claim to
                # license the very read the fact existed to justify.
                if written_here & ((cond_names or {}).get(k) or set()):
                    merged_in[k] = frozenset()
                    merged_out[k] = frozenset()
                    continue
                acc_in = None
                for p in b.preds:
                    # A predecessor that reaches this block only by the
                    # condition having FAILED contributes nothing: the claim is
                    # vacuous on that path, and that is what makes it vacuous
                    # rather than what makes it false. **Skipping it is the whole
                    # mechanism** — counted as a claim, it intersects the
                    # implication away at the join after the first `if` and the
                    # second one has nothing left to use.
                    if (b.false_from or {}).get(p) == k:
                        continue
                    if facts[p].get(k) is False:
                        continue
                    # Every OTHER predecessor constrains, and a predecessor with
                    # no claim of its own constrains to NOTHING: it is a path on
                    # which no name is implied, and treating it as unconstraining
                    # would hand this block the other paths' names.
                    #
                    # …except on the FIRST round, where a predecessor that comes
                    # LATER in the block order is a loop's back edge and its
                    # claim is not computed yet. Counting it then is what makes a
                    # loop's body claim nothing: the body's only other way in is
                    # the loop header, and the meet of the header's claim with
                    # the empty claim the back edge carries is empty, so
                    # nothing is ever carried around the loop. Skipping it for one
                    # round leaves this block with the claim its FORWARD paths
                    # justify — an over-estimate, since a meet can only shrink —
                    # and every round after this one intersects the rest.
                    if rounds == 1 and p > b.index:
                        continue
                    cand = guarded_out[p].get(k) or frozenset()
                    acc_in = set(cand) if acc_in is None else (acc_in & cand)
                claim = frozenset() if acc_in is None else frozenset(acc_in)
                merged_in[k] = claim
                merged_out[k] = frozenset(claim | b.defs) if not b.kills \
                    else frozenset(claim | b.defs) - b.kills
            if merged_in != guarded_in[b.index]:
                guarded_in[b.index] = merged_in
                changed = True
            if merged_out != guarded_out[b.index]:
                guarded_out[b.index] = merged_out
                changed = True
        # A pathological CFG cannot loop forever (the sets only shrink and
        # there are finitely many), but the bound makes a cycle in the builder
        # a wrong answer rather than a hang. It is `len(blocks) + 2` because
        # that is what the stored-names pass has always used on this graph and
        # all three domains narrow along the same edges in the same rounds; the
        # implication pass cannot need more rounds than the pass whose answer it
        # reads.
        if rounds > len(blocks) + 2:
            break
    return out, facts, guarded_in


def read_before_store(fn, params: set = None, placed: set = None,
                      entry_facts: dict = None):
    """The first (name, line) a function reads that nothing stores first, or
    None.

    `params` is the function's incoming parameter names: they are stored by the
    CALLER, so reading one is never reading an unstored name.
    `placed` restricts the answer to names that have a home at all — a name
    with no home is `check_module_symbols`' refusal to make, and this one
    would be a second, worse message about the same name.

    `entry_facts` is `{name: literal-node}` for the MODULE-LEVEL constants that
    hold at the function's first instruction (`module_entry_literal_facts`), and
    it is what decides a loop whose iterable is a module-level literal sequence
    or whose range bound is a module-level integer: without it the preheader
    walk starts empty and such a loop is `'maybe'`, so its target stays defined
    and a read after it answers the caller's leftover. A name the function
    itself binds must NOT be passed — see the caller.

    **THE ALGORITHM, and what it is worth.** A "definitely stored" fixpoint
    over the function's CFG: `_build_cfg` cuts the body into basic blocks once,
    and `_definitely_stored` iterates a name into a block only when EVERY path
    to that block stores it. A read is this defect when the name is in neither
    the block's IN set nor the statements preceding it inside the block.

    That is a change of question rather than a widening of the old one, and it
    is what closes the shape the statement-order walk could not see:

        def f(n):
            for i in range(3):
                if i:
                    t = 1
            printf("t=%d", t)

    `t` is stored SOMEWHERE in the body, so the old walk saw the store and the
    read as fine; whether the register holds 1 or the caller's leftover depends
    on which arm ran, and CPython raises `UnboundLocalError` when `i == 0`.

    **Two shapes the fixpoint gets right that a "count the arms" heuristic
    does not**, and they are the reason this is a real analysis rather than a
    rule:

    * a name stored in EVERY arm of an `if`/`elif`/`else` chain IS dominating —
      `if c: p = 1 else: p = 2` then `print(p)` is legal, returns 3, and the
      intersection over arms is exactly the rule;
    * the `for` target STAYS bound after its loop, because the target is a
      definition in the loop's HEADER and the join is reached from the header's
      exit edge — which is what keeps
      `for i in range(0, 100): if i > 3: break` then `return i` (returns 4, and
      is legal) out of the answer set. Deciding it needs "did this loop execute
      at least once", which the CFG answers for free and the old walk could
      not.

    `try`/`except`/`else`/`finally`, `break` out of one arm of a loop, a
    `match` with a wildcard arm and a `del` on one path are all ordinary edges
    here rather than cases, which is what
    `FORMAL_read_before_store_dominating_store` asked for: it warned
    that a partial rule "fires on some of them and not others is worse than
    none in a specific way — it makes the corpus look covered".

    A statement shape the builder does not recognise becomes a leaf statement
    in its block, so it contributes no edge and no definition: an unknown shape
    is a silence rather than a wrong answer, and the direction is the safe one
    because the fixpoint is initialized from the top.

    **And a third domain, for the shape dominance alone cannot see.** A name
    read under a condition that an EARLIER test of the same condition already
    decided:

        is_tuple = var.startswith('(') and var.endswith(')')
        if is_tuple:
            var_names = gen._split_top_level_comma(inner)     # stores
        if is_tuple:
            emit(gen._cname(var_names[0]))                    # reads

    Every path reaching the second test passed the first, so the name is
    stored, and the CFG cannot say so: the join intersects the arm that stores
    with the arm that does not. `read_before_store` therefore also accepts a
    name that a CONDITION FACT holding at this point IMPLIES — see
    `_definitely_stored`'s third domain and `_cond_key` for what a fact may be
    keyed on and why a call is not one."""
    params = set(params if params is not None
                 else (getattr(fn, "params", None) or ()))
    params = {p[0] if isinstance(p, (tuple, list)) and p else p for p in params}
    placed = None if placed is None else set(placed)
    # Names this function cannot be asked about: a `global`/`nonlocal`
    # declaration moves the storage out of the frame entirely, and a
    # comprehension's targets are scoped to their own expression.
    declared_global: set = set()
    for node in iter_nodes(getattr(fn, "body", None) or []):
        if type(node).__name__ in ("GlobalStmt", "NonlocalStmt"):
            declared_global |= {n for n in (getattr(node, "names", None) or ())}

    # Names a COMPTIME statement's expressions mention. They are excluded, and
    # the reason is the ordering the build enforces rather than a subtlety of
    # this walk: a `comptime X = f(coefficients)` that does not fold leaves
    # `coefficients` with no compile-time value, and the refusal for THAT is
    # `model.comptime_fold_refusal`, which says what to do about it ("make the
    # initializer a literal … or bind it with an ordinary `var`"). A build
    # that reported the read instead would be reporting a symptom of a
    # construct it has a better-worded refusal for — measured on
    # `std/math/polynomial.mojo:86`, where `comptime num_coefficients =
    # len(coefficients)` is the real finding and "coefficients is read before
    # anything stores it" is not.
    comptime_names: set = set()
    for node in iter_nodes(getattr(fn, "body", None) or []):
        if type(node).__name__ not in ("ComptimeVarStmt", "ComptimeForStmt",
                                       "ComptimeIfStmt", "ComptimeAssertStmt"):
            continue
        for fname in ("value", "iterable", "condition", "msg"):
            comptime_names |= set(_expr_reads(getattr(node, fname, None), set()))

    found: list = []

    def note(name, line):
        if found:
            return
        if name in params or name in declared_global:
            return
        if name in comptime_names:
            return
        if placed is not None and name not in placed:
            return
        found.append((name, line))

    def walk_expr(e, live):
        for name, ln in _expr_reads(e, live).items():
            note(name, ln if ln is not None else getattr(e, "line", None))

    def walk_stmts(stmts, live):
        """The reads of a straight-line run, in order, updating `live`.

        The per-statement rules are the old walk's, unchanged and for the same
        reasons — they are about what ONE statement does, and the old walk was
        right about all of them. What changed is what `live` starts as: a
        block's IN set rather than a running set threaded through the whole
        function. The `if`/`while`/`for`/`try` arms are not here at all, because
        the CFG has already accounted for them by the time a block is walked."""
        live = set(live)
        for s in (stmts or []):
            kind = type(s).__name__
            if kind == "AssignStmt":
                # The VALUE is read before the target is written: `x = x + 1`
                # is the canonical case, and reading the value after adding
                # the target would make it look initialised.
                walk_expr(getattr(s, "value", None), live)
                live |= _store_names(getattr(s, "target", None))
                continue
            if kind == "AugAssignStmt":
                # `x += 1` READS x. An augmented assignment to a name nothing
                # stored is the same defect as `x = x + 1` with a shorter
                # spelling.
                walk_expr(getattr(s, "target", None), live)
                walk_expr(getattr(s, "value", None), live)
                live |= _store_names(getattr(s, "target", None))
                continue
            if kind == "VarDecl":
                walk_expr(getattr(s, "value", None), live)
                n = getattr(s, "name", None)
                # The same rule `_cfg_block_defs` states, and for the same
                # reason: `var a: Int` has no `=`, so it stores nothing, and a
                # fixpoint that counted it as a definition could not report the
                # read that follows. One reader of "does this statement define
                # its name" would be better than two, but the two live in
                # different halves of this module and the guard is a sentence
                # either way -- see `_cfg_block_defs`'s docstring.
                if isinstance(n, str) and getattr(s, "value", None) is not None:
                    live.add(n)
                continue
            if kind == "MultiAssignStmt":
                walk_expr(getattr(s, "value", None), live)
                for t in (getattr(s, "targets", None) or []):
                    live |= _store_names(t)
                continue
            if kind in ("ForStmt", "ComptimeForStmt"):
                # The ITERABLE is read before the target exists (a `for` target
                # is a fresh binding, not a read of an enclosing one), and the
                # target is bound BEFORE the body runs — except for a range
                # that yields nothing, which binds it not at all:
                # `_loop_target_defs`, which is the same reader
                # `_cfg_block_defs` uses, because a graph and a walk that
                # disagree about one definition is a refusal that appears and
                # disappears with which of them runs.
                walk_expr(getattr(s, "iterable", None), live)
                live |= _loop_target_defs(s)
                continue
            if kind == "WhileStmt":
                walk_expr(getattr(s, "condition", None), live)
                continue
            if kind == "IfStmt":
                walk_expr(getattr(s, "condition", None), live)
                continue
            if kind == "MatchStmt":
                walk_expr(getattr(s, "subject", None), live)
                continue
            if kind == "ComptimeIfStmt":
                walk_expr(getattr(s, "condition", None), live)
                continue
            if kind == "WithStmt":
                for it in (getattr(s, "items", None) or []):
                    walk_expr(getattr(it, "expr", None), live)
                    a = getattr(it, "alias", None)
                    if isinstance(a, str):
                        live.add(a)
                continue
            if kind == "TryStmt":
                for h in (getattr(s, "handlers", None) or []):
                    n = getattr(h, "name", None)
                    if isinstance(n, str):
                        live.add(n)
                continue
            if kind == "DelStmt":
                # `del x` READS x, and a name nothing stored is the same case.
                for t in (getattr(s, "targets", None) or []):
                    walk_expr(t, live)
                for t in (getattr(s, "targets", None) or []):
                    live -= _store_names(t)
                continue
            if kind == "ComptimeVarStmt":
                walk_expr(getattr(s, "value", None), live)
                live |= _store_names(getattr(s, "target", None))
                continue
            if kind in ("FunctionDef", "StructDef", "TraitDef", "LambdaExpr"):
                # A nested definition's body is a DIFFERENT frame with its own
                # parameters, and its locals are not this function's.
                continue
            if kind in ("ReturnStmt", "ExprStmt"):
                walk_expr(getattr(s, "value", None), live)
                continue
            if kind == "RaiseStmt":
                walk_expr(getattr(s, "value", None), live)
                continue
            if kind == "AssertStmt":
                walk_expr(getattr(s, "value", None), live)
                walk_expr(getattr(s, "msg", None), live)
                continue
            if kind in ("BreakStmt", "ContinueStmt", "Pass", "GlobalStmt",
                        "NonlocalStmt"):
                continue
            # Anything else: walk its expressions rather than ignore it, so an
            # unrecognised statement shape is a silence rather than a wrong
            # answer.
            for f in getattr(s, "__dataclass_fields__", ()) or ():
                if f in ("line", "col"):
                    continue
                v = getattr(s, f, None)
                if isinstance(v, (F.IfStmt, F.WhileStmt, F.ForStmt, F.WithStmt,
                                  F.TryStmt, F.MatchStmt, F.ReturnStmt,
                                  F.ExprStmt, F.AssertStmt, F.RaiseStmt,
                                  F.DelStmt, F.AssignStmt, F.AugAssignStmt,
                                  F.VarDecl, F.MultiAssignStmt, F.FunctionDef,
                                  F.StructDef, F.TraitDef, F.LambdaExpr)):
                    walk_expr(v, live)
                else:
                    walk_expr(v, live)

    blocks, entry, cond_names = _build_cfg(getattr(fn, "body", None) or [],
                                           entry_facts)
    stored_in, facts_in, guarded_in = _definitely_stored(blocks, entry, params,
                                                         cond_names)
    # Blocks in index order, so the finding is the FIRST in SOURCE order rather
    # than whatever order the builder happened to finish them in — a diagnostic
    # that names a later line when an earlier one is the same defect sends the
    # reader to the wrong place.
    for b in sorted(blocks, key=lambda x: x.index):
        if b.index == entry:
            continue
        live = set(stored_in.get(b.index, set()))
        # A name a fact that HOLDS HERE implies is stored here. This is the
        # correlated-condition half: `if c:` stores, then `if c:` reads, and the
        # two tests are the same test because nothing wrote the condition. The
        # implication is only consulted for a fact this block's IN set says is
        # TRUE, which is what keeps the rule from licensing a read in the
        # `else` arm of the very `if` that established it.
        here = guarded_in.get(b.index) or {}
        for key, holds in (facts_in.get(b.index) or {}).items():
            if holds is True:
                live |= set(here.get(key) or ())
        walk_stmts(b.stmts, live)
        if found:
            break
    return found[0] if found else None


def _block_stmt_exprs(s) -> list:
    """The read-position expressions of a statement that is a BLOCK'S OWN
    statement, as opposed to a statement in one of its arms.

    A block's `stmts` are the straight-line statements it holds plus, for a
    control-flow block, the control statement ITSELF — whose arms are separate
    blocks, each visited on their own. So this answers "what does this block's
    own text read" and deliberately does not descend into arm bodies: a reader
    that did would attribute a nested arm's read to the enclosing block, and
    the enclosing block's entry facts are not the arm's.

    The per-kind list mirrors `read_before_store`'s `walk_stmts` read rules —
    an `AssignStmt`'s TARGET is a store, not a read, and a `VarDecl` without an
    initialiser reads nothing — because the two must count the same reads: this
    list decides where a loop target is read in a possibly-unbound state, and
    `read_before_store` decides whether that read is accepted at all. A graph
    and a walk that disagree about one read is a check that appears and
    disappears with which of them ran."""
    kind = type(s).__name__
    if kind == "AssignStmt":
        return [getattr(s, "value", None)]
    if kind == "AugAssignStmt":
        return [getattr(s, "target", None), getattr(s, "value", None)]
    if kind == "VarDecl":
        return [getattr(s, "value", None)]
    if kind == "MultiAssignStmt":
        return [getattr(s, "value", None)]
    if kind in ("ForStmt", "ComptimeForStmt"):
        return [getattr(s, "iterable", None)]
    if kind == "WhileStmt":
        return [getattr(s, "condition", None)]
    if kind == "IfStmt":
        return [getattr(s, "condition", None)]
    if kind == "MatchStmt":
        return [getattr(s, "subject", None)]
    if kind in ("ReturnStmt", "ExprStmt", "RaiseStmt"):
        return [getattr(s, "value", None)]
    if kind == "AssertStmt":
        return [getattr(s, "value", None), getattr(s, "msg", None)]
    if kind == "DelStmt":
        return list(getattr(s, "targets", None) or [])
    return []


def _stmt_store_names(s) -> set:
    """The names one statement STORES — `_cfg_block_defs`'s rules, one
    statement at a time, so a block's per-statement walk and the block's `defs`
    cannot disagree about a `VarDecl`'s missing initialiser or a `WithStmt`'s
    alias. A `del` stores nothing: on this path a bare `del` is a no-op at run
    time (the image keeps the name's value), which is the same reason the
    possibly-unbound dataflow above lets a `kills` set contribute nothing."""
    kind = type(s).__name__
    if kind in ("AssignStmt", "AugAssignStmt"):
        return _store_names(getattr(s, "target", None))
    if kind == "VarDecl":
        n = getattr(s, "name", None)
        if isinstance(n, str) and getattr(s, "value", None) is not None:
            return {n}
        return set()
    if kind == "MultiAssignStmt":
        out: set = set()
        for t in (getattr(s, "targets", None) or []):
            out |= _store_names(t)
        return out
    if kind == "WithStmt":
        out = set()
        for it in (getattr(s, "items", None) or []):
            a = getattr(it, "alias", None)
            if isinstance(a, str):
                out.add(a)
        return out
    if kind == "TryStmt":
        out = set()
        for h in (getattr(s, "handlers", None) or []):
            n = getattr(h, "name", None)
            if isinstance(n, str):
                out.add(n)
        return out
    if kind == "ComptimeVarStmt":
        return _store_names(getattr(s, "target", None))
    return set()


def loop_bound_flags(fn, params: set = None) -> dict:
    """`{name: (id(ForStmt), …)}` for the loop targets this function must
    guard with a runtime bound flag, or `{}`.

    **The question.** `read_before_store` accepts a read of a `for` target
    after a loop whose emptiness is a run-time fact (`'maybe'`), because
    refusing would drop `last(4)`-shaped programs CPython runs. The accepted
    read is still the defect when the range turns out empty: nothing stores
    the target, so the read answers the caller's leftover. The build cannot
    decide which way a given call goes, so the EMITTED image has to ask at
    run time — one flag per flagged name, zero at entry, set by every store of
    the name (a loop's `init:` is a store, a comprehension's per-element
    store is a store), and branched on at a read that may be unbound. This
    reader decides which names that is; the two backends read the same answer
    from it, so the two architectures flag the same loops.

    **A name is flagged only when all three of these hold of one of its
    `'maybe'` loops, and the safe direction is the one that says so:**

    1. the target is a single name — a tuple target is not a word this value
       model can flag, and a `global` target is not this frame's storage at
       all;
    2. **every path does NOT store the name before the loop** — the
       `_definitely_stored` dataflow, the same one `read_before_store` runs,
       is the reader, so the two cannot answer "is this name bound here"
       differently. A name every path stored before the loop holds a value on
       the zero-iteration edge too, so its check would never fire and the
       flag stays out of the image (which is where the idiomatic
       `i = 0; for i in range(…)` stays). A name stored on SOME path is
       flagged, not excluded: the store that path makes is the store that
       SETS the flag, and the other path is the one the check fires for.
       The parameters are the dataflow's seed, and that is what keeps a
       parameter target out for the sharper reason the emitter states — the
       prologue's argument store is the one store that does not run the flag
       hook, so a flag there would fire on a path that holds the caller's
       word;
    3. the name is read in a block where it may be unbound. Without it a loop
       whose target is never read in that state would allocate a flag nothing
       branches on — dead code in an image whose every word is walked by the
       proof generators.

    The read test uses the "possibly unbound" dataflow, the dual of
    `_definitely_stored`: a name is possibly unbound at a block's entry when
    some path to it left it so. It is initialised from the TOP and narrowed,
    because the answer being computed is "may be unbound" and a name the
    analysis failed to track as unbound must not be assumed bound — the
    opposite of `_definitely_stored`'s question, which is why it is a second
    array rather than the negation of the first. The header block of a tracked
    loop contributes its defs WITHOUT the loop target, because on the
    zero-iteration edge the header does not bind it — that binding happens on
    the edge into the body (the body's first block `seed`), and a header that
    bound it would silence exactly the path this flag exists for. `del`
    contributes nothing, because a bare `del` on this path is a no-op at run
    time and the image keeps the name's value.

    Module-level entry facts are deliberately NOT passed to the preheader
    walk: a fact the walk cannot see makes a loop `'maybe'` rather than
    decided, which flags MORE loops, and a flagged loop whose range turns out
    non-empty never takes its check — the dead-check direction is the safe
    one, while a module fact the emitter sees and `read_before_store` does not
    (or vice versa) would be two machines answering one loop differently.
    See the bug history for the residual this reader closes and the cases it deliberately leaves.
    """
    params = set(params if params is not None
                 else (getattr(fn, "params", None) or ()))
    params = {p[0] if isinstance(p, (tuple, list)) and p else p for p in params}
    body = getattr(fn, "body", None) or []
    declared_global: set = set()
    for node in iter_nodes(body):
        if type(node).__name__ in ("GlobalStmt", "NonlocalStmt"):
            declared_global |= {n for n in (getattr(node, "names", None) or ())}

    blocks, entry, _cond_names = _build_cfg(body, None)
    candidates: list = []
    hdr_target: dict = {}
    for s in (n for n in iter_nodes(body) if isinstance(n, F.ForStmt)):
        t = getattr(s, "target", None)
        if not (isinstance(t, str) and t.isidentifier()):
            continue
        if t in declared_global:
            continue
        header = None
        for b in blocks:
            if len(b.stmts) == 1 and b.stmts[0] is s:
                header = b
                break
        if header is None:
            continue
        consts, seqs = _preheader_facts(blocks, header.index, entry, None)
        if _for_emptiness(s, consts, seqs) != _MAYBE_RUNS:
            continue
        candidates.append((s, t, header))
        hdr_target[header.index] = {t}
    if not candidates:
        return {}
    tracked = {t for _s, t, _h in candidates}

    # Definitively stored on EVERY path to the header: `_definitely_stored`,
    # the same dataflow `read_before_store` runs, asked over the same CFG, so
    # the two answers to "is this name bound here" cannot drift. A name every
    # path stored before the loop holds a value on the zero-iteration edge too,
    # so its check would never fire and the flag stays out of the image — which
    # is also where the idiomatic `i = 0; for i in range(…)` stays flag-free.
    # The seed is the parameters, and it is what keeps a parameter target
    # unflagged for the sharper reason the emitter states: the prologue's
    # argument store is the one store that does not run the flag hook. A name
    # stored on SOME path is NOT excluded — the store that path makes is the
    # store that SETS the flag, and the other path is the one the check fires
    # for, which is the mixed shape the "possibly stored" draft used to leave
    # as garbage.
    stored_in, _facts_in, _guarded_in = _definitely_stored(
        blocks, entry, params, _cond_names)

    # Possibly unbound at entry, the dual: top-initialised and narrowed.
    mu: dict = {b.index: set(tracked) for b in blocks}
    changed = True
    while changed:
        changed = False
        for b in blocks:
            merged = None
            for p in b.preds:
                b_p = blocks[p]
                stored = b_p.defs - hdr_target.get(p, set())
                e = mu[p] - stored
                merged = set(e) if merged is None else (merged | e)
            merged = set(tracked) if merged is None else merged
            merged -= b.seed
            if merged != mu[b.index]:
                mu[b.index] = merged
                changed = True

    # A read in a MAYBE state, per NAME. The walk is per STATEMENT within a
    # block rather than per block, because a block's entry state and the state
    # at its last read differ: `q = 7` and `print(q)` are one block whose entry
    # says `q` may be unbound (the zero-iteration edge) but whose read is after
    # the store, so the statement order is what decides. The store rules are
    # `_cfg_block_defs`'s, one statement at a time, so the two cannot count a
    # `VarDecl`'s missing initialiser differently.
    maybe_reads: set = set()
    for b in blocks:
        cur = set(mu[b.index])
        for s in b.stmts:
            for e in _block_stmt_exprs(s):
                for n in _expr_reads(e, set()):
                    if n in tracked and n in cur:
                        maybe_reads.add(n)
            cur -= _stmt_store_names(s)

    out: dict = {}
    for s, t, header in candidates:
        if t in stored_in.get(header.index, set()):
            continue
        if t not in maybe_reads:
            continue
        out.setdefault(t, []).append(id(s))
    return {t: tuple(ids) for t, ids in out.items()}


def read_before_store_refusal(name: str, fn_name: str, line) -> str:
    """The one-line diagnostic for a name read before anything stores it.

    Names the language's own error, because that is the answer the source has
    and the reader is comparing against: CPython raises
    `UnboundLocalError` inside a function and `NameError` at module level for
    this exact program, so a reader who has run it under CPython is looking
    for that. It also says WHY the backend cannot raise it, which is the part
    that is specific to this path and the part that would otherwise be
    re-derived: the emitted image has no way to mean "unbound", so the value
    would be a register nobody wrote.

    The `line` is included because the defect is invisible in review — a
    program that reads a name it never stores looks like ordinary code, and
    the wrong answer is a build-dependent word rather than an error, so
    without a location the reader has nothing to go on."""
    where = f" at line {line}" if line else ""
    who = f"{fn_name}: " if fn_name else ""
    return (
        f"{who}{name!r} is read{where} before anything in this function "
        f"stores it, and CPython raises UnboundLocalError for that program "
        f"(NameError at module level). This path cannot raise it: the "
        f"register allocator gives {name!r} a home because the function "
        f"assigns it somewhere, and the emitted image has no way to mean "
        f"\"unbound\" — so the read would return whatever the CALLER left in "
        f"that register, a word that changes with the build and differs "
        f"between the two backends. Store {name!r} before reading it, or "
        f"declare it where it is written.")


def is_generic(fn) -> bool:
    return bool(getattr(fn, "comptime_params", None))


def specialization_call_refusal(name: str) -> str:
    """The refusal for `name[a, b](...)` when `name` is not a function here.

    ARCH-FREE and asked by BOTH backends from `_emit_call`, for the same
    reason `gimple_runtime_refusal` is: one construct, one language
    implementation, one answer — an architecture that answered differently
    about the same call would be the two-machines-one-language failure this
    file exists to prevent.

    A comptime specialization is a CALL whose brackets bind the generic's
    comptime parameters, and on this path those parameters are ordinary
    LEADING arguments (see the calling convention above): the call site
    evaluates the brackets and passes them first. That is a decision about a
    signature, so it can only be made against a declaration — and when the
    name is not a function this unit compiles, there is none. Three spellings
    reach here, and the third is the one the first wording of this sentence
    got wrong:

      * the name is a generic of ANOTHER module. Its instantiation is the
        boundary symbol (doc/ABI.md §Generics), one per set of type arguments,
        and `formal/monomorph.py` compiles the ones an importer asks for into
        that module's own library and REWRITES the call site to the mangled
        name — so a call that arrives here is one whose brackets named no
        instantiation: an argument that is a value rather than a type, a
        dotted `module.name[…]`, or a template in a type ANNOTATION rather
        than a callee position.
        `bugs/formal/FORMAL_generic_monomorph_scope.md` lists each with its next step.
      * the name is a function of another module whose generic parameter is
        IMPLICIT — `def name(x: Box[T])`, with the parameter written in the
        SIGNATURE and no bracket to bind. There the type is INFERRED from the
        call, so a bracket the source wrote is not read at all; the repair is
        the bare call, and it is the same program (measured: the identical
        module with `def unbox(t: Box[T])` builds as `unbox(b)` and is refused
        as `unbox[Int](b)`, both architectures). This is why the sentence must
        not tell the reader to write `name[<a type>](…)` — for this shape that
        is the spelling already on the line.
      * the name is an ordinary VALUE and the brackets are a subscript. A
        subscript of a value is not a call this path can name at all.

    **The alternative is worse than a wrong number, and it is measured.**
    Both backends flatten the callee to the base name and then, for a callee
    this unit does not compile, emit the call with the brackets DROPPED:
    `plain[3](5)` becomes a plain `plain(5)`. Measured on arm64 — a module
    exporting `def plain(v): return v + 100`, and a program that wrote
    `plain[3](5)` — the image built, ran, and printed 105. Nothing in the
    source says 105, and no link line would have caught it, because `plain`
    really is a defined symbol; the bracket is simply gone. Refused here
    instead, which is the whole difference between a build error and a
    program that answers a question nobody asked.
    """
    if "." in (name or ""):
        return dotted_specialization_refusal(name)
    return (
        f"{name}[…](…) calls a name this unit does not compile, so the "
        f"brackets cannot be bound. If `{name}` is a generic of another module "
        f"whose parameters are spelled in brackets (`def {name}[T](…)`) then "
        f"its instantiation is the boundary symbol, one per set of type "
        f"arguments (doc/ABI.md §Generics), and this path DOES instantiate the "
        f"ones an importer asks for — `formal/monomorph.py` compiles each into "
        f"that module's own library and rewrites the call to the mangled name — "
        f"so a call arriving here asked for none: its brackets named no type "
        f"argument, or named a value rather than a type (`plain[3](5)`, where "
        f"the bracket is an argument and not a slot), or named a TYPE ARGUMENT "
        f"on a function whose type parameter is INFERRED from its parameter "
        f"types — `def {name}(t: Box[T]) -> T` called as `{name}[Int](b)` — "
        f"which this path reads off the ARGUMENTS rather than off a bracketed "
        f"declaration, so no boundary symbol is emitted for it. That last shape "
        f"is CORRECT SOURCE and this path is short: Mojo infers a template "
        f"call's type arguments, so call it WITHOUT the bracket — write "
        f"`{name}(…)`, which is the same program (`{name}(b)` with "
        f"`b: Box[Int]`) and is lowered (for that shape the bracketed call is "
        f"refused and the inferred one builds and answers CPython on both "
        f"architectures). **Do not add `[<a type>]` — that is the spelling that "
        f"arrived here.** The ways this can still be reached, with the spelling "
        f"that works for each, are in bugs/formal/FORMAL_generic_monomorph_scope.md. "
        f"If `{name}` is instead an ordinary value then the brackets are a "
        f"subscript, which is not a call this path can name at all. Refused "
        f"rather than emitted with the brackets dropped: that builds, runs, and "
        f"returns a number the source never wrote, with nothing on the link "
        f"line to catch it"
    )


def dotted_specialization_refusal(name: str) -> str:
    """The refusal for a bracketed callee spelled THROUGH A MODULE.

    `import lib as L`, then `L.Pair[Int]()`, and this build cannot bind it —
    not because no type argument was named (it names one perfectly well) and
    not because `L` is not exported, but because the ONE recogniser of a
    bracketed callee cannot see a dotted base.

    **A whole function and not a clause of `specialization_call_refusal`,
    because every sentence of the bare-name text is FALSE about this program.**
    It was handed the ROOT of the dotted chain, so `name` was `L`, and the
    message read "`L[…](…)` … If `L` is a generic of another module … write it
    as `L[<a type>](…)`": three claims about a program that says none of them.
    `L` is the MODULE, so it is not a generic of one; `L[<a type>]` is not a
    spelling of anything; and the "the call asked for no instantiation" clause
    is exactly the diagnosis this case needs to NOT give, because the brackets
    named a type argument and the reason the call arrived here is the
    recogniser. That is the `refuse_without:` class of defect this repository's
    own discipline names — a repair that is wrong about correct code — and the
    fix is a message that names the module, the template, the reason and a
    spelling that works.

    **The reason is stated rather than implied, because it is the useful part.**
    `mojo/middle/comptime.specialization_name` answers `None` for a dotted base
    BY DESIGN: both backends' `_specialization_of` and
    `formal/model.py::subscript_callee_names` consult that one function, and a
    second recogniser that disagreed with it would bind the call to the WRONG
    MODULE's instantiation — a wrong answer rather than a refusal, which is the
    one direction this backend must never take. So the dotted application is not
    a gap in a message, it is a gap in the mechanism, and §2 of
    `bugs/formal/FORMAL_generic_monomorph_scope.md` is where it is written down with
    the ABI decision it needs.

    **The remedy is the one spelling measured to work, and nothing else is
    claimed.** `from pairlib import Pair` — the module's OWN name — then
    `Pair[Int]()`, which builds, runs and answers CPython on both architectures
    (`test_formal_monomorph.py`'s two rows here). The ALIASED form is NOT
    claimed: `from pairlib import Pair as P` then `P[Int]()` was measured on
    this tree and is refused with `specialization_call_refusal`, because the
    demand walk reads `P` where the template is `Pair` and a struct template's
    instantiation is emitted under the mangled name. §2 of the doc says the
    alias "maps back" for a FUNCTION template's demand; it is not true of this
    one, so the message does not say it.
    """
    module, _, leaf = name.rpartition(".")
    return (
        f"{name}[…](…) is a bracketed callee spelled THROUGH A MODULE, and "
        f"`{module}` is the module while `{leaf}` is the template — so this is "
        f"not a name this unit fails to compile, it is a spelling of a "
        f"specialization this build cannot yet recognise. The brackets name a "
        f"type argument perfectly well; what is missing is the reader. "
        f"`mojo/middle/comptime.specialization_name` is the ONE recogniser of "
        f"a bracketed callee — both backends' `_specialization_of` and "
        f"`formal/model.py::subscript_callee_names` ask it — and it answers "
        f"`None` for a dotted base BY DESIGN, because a second recogniser that "
        f"disagreed with it would bind the call to the wrong module's "
        f"instantiation. Bind the template by its bare name instead — "
        f"`from <the module> import {leaf}`, spelled with the MODULE'S OWN name "
        f"rather than the `{module}` alias — and call `{leaf}[…](…)`. That is "
        f"the same program, and it builds, runs and answers CPython on both "
        f"architectures; the ALIASED form (`import … as {module}` then "
        f"`from {module} import {leaf}`, or `{module}` bound to `{leaf}`) was "
        f"measured on this tree and is still refused, so do not stop there. "
        f"The dotted application itself, and the ABI question a fix needs, are "
        f"§2 of bugs/formal/FORMAL_generic_monomorph_scope.md. Refused rather than "
        f"emitted with the brackets dropped: that builds, runs, and returns a "
        f"number the source never wrote, with nothing on the link line to catch "
        f"it"
    )


def callee_is_a_module_slot_function(name: str, function_names) -> bool:
    """True when `name(...)` is a call through a module global's slot word.

    The second shape of "a callee this unit has no symbol for", beside
    `callee_is_a_bound_value`'s parameter-or-local. A module-level
    `var g = dbl` with `global g` in a function gives `g` a `__DATA` slot
    (`collect_global_slots`), and the slot's word is the function's entry
    address — the module body stores it, and a read of `g` as a value already
    lowers to a load of that slot. But `callee_is_a_bound_value` deliberately
    subtracts `global_names_bound_in`, so a `global` name is NOT a bound value
    and `g(21)` took the extern path and emitted a `BL g` against a symbol
    nothing provides — refused four stages later by the bind audit with a
    message about the link line rather than about the call. Measured, both
    architectures: `fire.py run` answers 42 and the image refused to build.

    The evidence is the slot's OWN module-level statement, because that is the
    only place the value's shape is stated: `GlobalSlot.site` is the statement
    and its `value` is what the module binds the name to. A function NAME there
    is a code address; anything else (an integer, a call, a container) is not
    this predicate's business and is left to the extern path, so an
    integer-valued global called as a function keeps its refusal rather than
    becoming a branch through a number. `function_names` is the unit's own
    definitions — the same table `name not in self._functions` reads — so a
    name bound to something this unit does not compile is not claimed here.
    """
    slot = module_slot(name)
    if slot is None:
        return False
    value = getattr(getattr(slot, "site", None), "value", None)
    return (isinstance(value, F.IdentExpr)
            and value.name in (function_names or ()))


def callee_is_a_bound_value(fn, name: str) -> bool:
    """True when `name` is a name `fn` binds, so it cannot be a symbol.

    The question `is_extern = name not in self._functions` cannot ask, and the
    gap it leaves is the one construct whose callee this build KNOWS it does not
    have a symbol for: `func(i)` inside a function that received `func` as a
    parameter. `func` is not a function of this unit, so the extern path takes
    it — and the extern path's whole job is to emit a call to a symbol, so it
    emitted a call to a symbol named after the parameter. The image was then
    refused by the bind audit (`build.py::_audit_bound_symbols`) with a message
    about a symbol nothing on the link line provides, which is true and says
    nothing about the construct: measured on
    `stdlib/std/algorithm/backend/cpu/map.mojo`, whose only statement is
    `func(i)`, and which this classified as `not-answerable/unresolved-extern`
    on both architectures rather than as the codegen gap it is.

    A name a function BINDS is a value on this path — a register, a spill slot,
    a receiver field's frame, a `__DATA` word — and a value is one 64-bit word,
    so the callee it could hold would be a code address this build cannot
    prove. That is a refusal about the representation, and it is asked at the
    call site where the construct is, not four stages later by a link audit.

    **The reader is the allocator's own, and that is the point.** Asking a
    second walk "does this body bind this name" would be a second answer to a
    question `_collect_var_names` has already answered for the register file,
    and the two would disagree on exactly the shapes that disagree — a name
    written only inside a branch that never runs, a comprehension's loop
    variable — which is the false refusal `formal/build.py::_names_bound_in`
    documents. So this asks `bound_names_in_order`, the walk both emitters
    allocate from, and subtracts `global_names_bound_in` for the same reason
    they do: a name declared `global` is not a local of the function, and
    `global f; f()` really is a call to the module's function.

    Returns False for a name `fn` does not bind, which is every ordinary case:
    a callee is not a value, and this is a guard on the extern path rather than
    a new question asked of every call."""
    if not name or fn is None:
        return False
    params = [p[0] if isinstance(p, (list, tuple)) else getattr(p, "name", None)
              for p in (getattr(fn, "params", None) or [])]
    bound = {p for p in params if isinstance(p, str)}
    try:
        from mojo.middle.boundnames import bound_names_in_order
        bound |= {n for n in bound_names_in_order(
            getattr(fn, "body", None) or [], [])
            if isinstance(n, str)}
    except Exception:
        # No answer from the allocator's walk means no answer here either: the
        # refusal belongs to a name we have EVIDENCE is bound, and guessing
        # would refuse a working program.
        pass
    bound -= global_names_bound_in(fn)
    return name in bound


def sole_field_call_refusal(spelling: str, struct: str, chain: str, root: str,
                            fn_name: str = None) -> str:
    """Why `c.f(5)` is a call of a VALUE: the callee is the struct's own field.

    ARCH-FREE, and asked from the shared pass — `formal/build.py`'s
    `_rewrite_self_fields`, at the rewrite that would have lost the spelling —
    rather than from an emitter.  The emitter is the wrong place, and the reason
    is that the rewrite that keeps `self.f` and `self` one storage used to
    collapse the CALLEE as well: by the time a backend saw `c.f(5)` the node it
    held was `IdentExpr('c')`, and the only name it could print was `c`.  A
    refusal naming a name the reader did not write is
    `bugs/formal/FORMAL_known_limits.md`'s failure mode — it costs a second build to
    discover that `f` is the field, and a reader who does not check concludes
    that `c` is the problem.  `callee_value_refusal` above is what a backend
    reaches for on the collapsed node and it is TRUE of it (`c` is a name the
    function binds), which is exactly why it had to be answered before the
    collapse rather than after it.

    **The refusal belongs to the REWRITE, because every chain it would collapse
    in callee position names FIELDS.**  `chain` is `_one_word_sole_field_chain`'s
    answer, which stops where the identity stops: a two-field struct in the slot
    is a FRAME, and `b.inner.v` is then a load at a frame base rather than a
    spelling of `b`.  So a callee this rewrite matches is a chain of field reads
    and nothing else — there is no spelling of it that names a method, because a
    method name is not a field name.  That is why one arm covers both the
    single-hop `c.f(5)` and the transitive `self._inner._k(5)`, and why nothing
    here asks whether the last step is a field or a method: once a METHOD is
    called through the field (`self._inner.get(5)`) the chain does not match,
    and `_rewrite_one_word_field_method_calls` has lifted that call by name
    before this pass runs.

    **CPython agrees, which is what makes this a refusal and not a limitation.**
    A field read is a value there too, so `c.f(5)` is
    `TypeError: 'int' object is not callable` — the source does not compute
    something else, it does not compute anything.  The two spellings this path
    CAN answer are named in the message, because "call a function of this unit by
    name" (the advice a call through a VALUE gets) sends the reader hunting for
    a function named `f` that does not exist.
    """
    who = f"{fn_name}: " if fn_name else ""
    return (
        f"{who}`{spelling}` is a call of a VALUE rather than of a function of "
        f"this unit: `{spelling}` is a read of `{chain}`, and a one-field "
        f"struct's receiver IS its field — `{chain}` is `{struct}`'s whole "
        f"value, so `{spelling}` and `{root}` are ONE 64-bit word here and the "
        f"word holds a value, which is not something this path can call. There "
        f"is no function value in it either: a code address is a word whose "
        f"target this build cannot establish, and a closure needs an "
        f"environment, which is a box this target has no allocator for. "
        f"CPython says the same about the source — a field read is a value "
        f"there as well, so `{spelling}` is a `TypeError: '… object is not "
        f"callable'` — and the two spellings this path CAN answer are a METHOD "
        f"call, `{root}.<method>(…)` with a method `{struct}` declares, and a "
        f"field READ, `{spelling}` without the call. Refused at the rewrite "
        f"that would have made it `{root}(…)`, a call of the RECEIVER: the "
        f"rewrite cannot tell a field read from a call of one, and an emitter "
        f"downstream could only see the name the rewrite had already "
        f"invented."
    )


# The kind constants live HERE, above every table that names one, because the
# string-method table below records what each method YIELDS and a table that
# had to spell "str" as a literal to dodge a forward reference would be one
# more place for the two spellings to drift apart. Their meaning is documented
# in full at the "What a value is" section further down, next to ValueKinds.
INT_KIND = "int"
STR_KIND = "str"
LIST_PREFIX = "list"

# A FRAME ADDRESS, as a kind rather than as prose.  It is the kind of a slot
# whose agreed declared type is a struct of this module whose receiver is the
# address of a frame of 8-byte slots (`struct_is_framed`), and it is a kind
# because the questions a kind is asked are exactly the questions a frame
# address answers differently from a plain word: `len` cannot read a count out
# of it, a string method cannot read bytes through it, and truthiness IS the
# identity test because a frame is never mapped at zero.
#
# It was not a kind before, and that is the whole of the wrong refusal it
# closes: with the slot unclassified, `len(self.inner)` said "the source does
# not say what this operand holds … Annotate it (`x: String`)" about a field
# declared `inner: Inner`, which is a frame address whose offset 0 is the
# struct's FIRST FIELD.  A refusal that is right for the wrong reason sends the
# next reader after a non-bug; this one sends them to annotate a field that is
# already annotated.
#
# IT IS NOT ENOUGH, on its own, and the reason is the largest hole this audit
# found: a kind is consulted by the operations that ASK for one, and the
# CONTAINER operations do not ask.  `r[i]`, `r[a:b]`, `x in r` and
# `for i in r` all take a base expression and emit the blob walk — read the
# count at offset 0, bounds-check against it, read elements at `base + 8 + 8k`
# — without ever consulting `ValueKinds`, because a blob's layout is the
# emitter's business and the emitter already knows the layout.  Handed a bare
# name that the frame-holder analysis says is a frame ADDRESS, every one of
# them therefore computed on a frame.  Measured on BOTH architectures, on a
# four-field struct with `a=11, b=22, c=33, d=44` written by running
# statements:
#
#     return r[0]                     →  22   (the SECOND field)
#     return r[1]                     →  33   (the THIRD field)
#     var t = r[0:2]; return 0        →  arm64 exit 1, x86-64 exit 0
#     for i in r: s = s + i           →  arm64 99, x86-64 53
#
# Two of those are numbers nobody wrote, and two DISAGREE between the
# architectures, which is the whole of the badness at once: plausible, silent,
# and not one language.  `frame_container_operand_refusal` below is the
# decision; the kind is the documentation of it.
FRAME_KIND = "frame"

# A TYPE, read as a VALUE.  It is a kind for the same reason `FRAME_KIND` is: the
# construct landed (a type is one 64-bit tag on this path — `type_tag` below, and
# `TYPE_VALUE_CASES` in `test_formal_run.py` runs the images) and the two places
# that mistake a tag for a number were both wrong in a way a reader cannot act
# on.
#
#   * `len(bool)` was refused with "the source does not say what this operand
#     holds … Annotate it (`x: String`)" — false about a program that spells the
#     operand as a type at the use site, and the advice is to annotate a name
#     that already has a type.
#   * `len(t)` where `t = bool` was refused with "an integer has no length" —
#     false, because `t` holds a TYPE TAG and the difference is the whole
#     subject of the construct.
#   * `xs[bool]` on a list BUILT, ran and died at the bounds check with nothing
#     printed (exit 1, no message, both architectures), because a tag is a
#     number to the emitter and an enormous one to the count it is checked
#     against.
#
# What a tag is NOT is a number, which is why this is its own kind and not a
# row of `INT_KIND`: `is_number_kind` is the one place that says "a tag prints
# as a number" (it is a word), and everything that asks "is this an integer?"
# — `len`, a string method, a container index — must keep saying no.
TYPE_KIND = "type"

# An IEEE-754 BINARY64 — a `double` — as a KIND, which is new and is the whole
# of what a `double` is on this path: **one 64-bit word holding its bit
# pattern.**  Not a new storage: a parameter, a frame slot, a struct field, a
# list element and a return value are all already one word, and that is why a
# `Float64` local, a `Float64` parameter and a `Float64` struct field all work
# without a word of change to the frame layout, the register allocator or the
# spill code.  What the kind adds is the refusal: before it, every one of those
# positions held an `INT_KIND` word, so `1.5 + 2.25` was `ADD` on two truncated
# zeros and `x < y` on a pair of bits, and both BUILT.
#
# It is its own kind and not a row of `INT_KIND` for the reason `TYPE_KIND` is:
# the two claim opposite things about the same word.  A word is either an
# integer or the pattern of a double, and `is_number_kind` — the one predicate
# that decides how a value PRINTS — must say no for this one, or `%d` reads a
# double's exponent field as a decimal.
#
# **Scope: binary64 only.**  A `Float32` is four bytes with a different
# exponent bias, and its bits are NOT a sub-pattern of a double's, so a word
# holding one cannot be a `FLOAT_KIND` here: `Float32` is deliberately not in
# `formal.types.FLOAT_TYPE_NAMES` and is refused by name rather than accepted
# and misread.  `float16`/`bfloat16` and the `float8_*` family are the same
# story.  See `bugs/formal/FORMAL_float_binary64_only.md`.
FLOAT_KIND = "float64"

# BYTES THE KERNEL SUPPLIED, as a kind, which is new and is the whole of what a
# `readdir(3)` name or a `getenv(3)` value is on this path: **a bare `char *` to
# NUL-terminated bytes that are not in the image.**  Every other text on this
# path is interned in `__TEXT,__text` and therefore ASCII by construction, which
# is the assumption the whole TEXT ENCODING block rests on; this kind is the one
# value that breaks it, and it breaks it in the direction that produces a number
# nobody wrote rather than a refusal.
#
# IT IS NOT A `bytes` AND IT IS NOT A `str`, and both of those are wrong in
# opposite directions, which is the whole reason it needs its own row:
#
#   * CPython's `len()` of `os.listdir(p)[0]` counts CHARACTERS.  A `strlen`
#     counts BYTES, and for an ASCII name the two are the same number, so the
#     byte answer looks right on every ordinary run.  Measured on BOTH
#     architectures, over a directory holding `plain` and `héllo`:
#     `sum(len(x) for x in listdir(d))` answered **11** where CPython answers
#     **10** — a UTF-8 `é` is two bytes and one character — green build, exit 0,
#     nothing on stderr.
#   * CPython's `os.listdir` does not hand back the bytes at all: it DECODES them
#     with `surrogateescape`, so the object is a `str` and a program that
#     compares it, prints it or takes a prefix of it is doing the right thing.
#     The BYTE reading is only CPython's answer for `os.fsencode`, which is a
#     different function.
#
# So the kind is a statement about PROVENANCE, and provenance is the only thing
# that decides anything here: every other `char *` in the image is text this
# build wrote down, so the ASCII assumption is sound for it, and this one is not
# because nothing in the source states what the kernel said.  That is also why it
# cannot be reached by a spelling the way `receiver_is_declared_bytes` reaches a
# `Pointer[UInt8]`: a loop target over `listdir(p)` has no declaration of its own
# (and that bug doc was deleted once fixed), and
# the annotation above it is `-> List[String]`, which is the honest word for a
# Python-level list of `str`.  The kind is therefore SEEDED where foreign bytes
# ENTER an image — `FOREIGN_BYTES_EXPORTS` below — and inherits through the
# container element axis (`list:fbytes`) exactly as `str` does.
#
# **Scope of what this changes, stated so a reader can check it.**  It is seeded
# at the host-module exports whose last writer was the kernel, and it is
# deliberately NOT a blanket annotation of `String`: exempting `String` would be
# the silent-wrong-answer direction, and it would be wrong for every `String` in
# this corpus that really does hold text, which is nearly all of them.  It also
# does not follow a value through a COMPOSITION — `os.path.join(getcwd(), p)` is
# a host-side `malloc` of the caller's bytes and a kernel's, and the kind of the
# result is the kind of the arguments, which this path does not track; the
# consequences are named in that bug document rather than left to be found.
# Everything that treats a `char *` as bytes keeps working, because every such
# question is asked through `string_operand_is_string` and that predicate is
# where this kind is admitted: `==`, `in`, `startswith`, `%s` and `print` all
# answer on the bytes, and CPython agrees on every one of them for a name the
# kernel supplied.  The ONE construct whose CPython answer is not a property of
# the bytes is a CHARACTER COUNT, and `len_operand_lowering` refuses it.
FOREIGN_BYTES_KIND = "fbytes"


def is_foreign_bytes_kind(kind) -> bool:
    """True when `kind` names bytes that came from outside the image.

    One predicate so the two backends, the value model and the build passes
    cannot each decide what "foreign" means, for the reason
    `is_byte_blob_kind` exists one level down: the question is about the KIND's
    content and a set of literal spellings is a second answer waiting to drift.
    """
    return kind == FOREIGN_BYTES_KIND


#: A C POINTER a declared return type established — the `char *getenv(const char
#: *)` an `external_call[…]` whose return type names a pointer to a byte hands
#: back.  It is a kind for the one reason `FOREIGN_BYTES_KIND` is: the value's
#: answer differs from a bare integer's in a place no consumer can recover from
#: the word itself (a `String(ptr)` built from the address, a `%s` that
#: dereferences it).
#:
#: **It is NOT `FOREIGN_BYTES_KIND`, and the difference is TRUTHINESS.** A
#: foreign-bytes value models a CPython `str` the kernel wrote, so `if name:`
#: asks whether the NAME is empty and `truthy_lowering` answers it with
#: `strlen`. A C pointer models the ADDRESS the function returned, so `if not
#: ptr:` asks whether it is NULL — and that is observable rather than academic:
#: measured on `test_formal_external_call.py::env_round_trip`, classifying a
#: `getenv` result as `FOREIGN_BYTES_KIND` made `if not ptr:` a `strlen(NULL)`
#: and the image died of SIGSEGV (exit -11) on both architectures, for the one
#: input the case exists for (an ABSENT variable). So the pointer's truthiness is
#: `TRUTHY_NONZERO` — the address's own zeroness, which is the null test — while
#: every other string-shaped question (`==`, `in`, `%s`, `print`, `String(ptr)`)
#: is answered on the bytes through `string_operand_is_string`, and `len` is
#: refused by `len_operand_lowering`, whose strlen answer would be a BYTE count
#: on a value whose CPython length is characters.
POINTER_KIND = "ptr"


# ── A FOREIGN-BYTE VALUE THROUGH A CALL BOUNDARY ────────────────────────────
#
# `FOREIGN_BYTES_KIND` is a compile-time fact about a value's PROVENANCE — what
# the kernel wrote into it — attached to the EXPRESSION that reads it (a
# `listdir` element, a loop target, a `getcwd()` call).  It is not a runtime tag
# on the word, so a call boundary drops it: `len(x)` where `x` is a directory
# entry is refused, but `nchars(x)` for `def nchars(s: String): return len(s)`
# emits a `strlen` INSIDE `nchars` and answers in BYTES.  The `String`
# annotation is the honest type and CPython agrees with it, and the call-site
# parameter table (`parameter_kinds_by_call_site`) asks about an UNANNOTATED
# parameter only, by design — so the annotated spelling had no reader at all.
#
# Measured 2026-10-14 on both architectures, over a directory holding `plain`
# and `héllo`, exit 0 and nothing on stderr — the same wrong number the direct
# refusal exists to prevent, reached one call further out:
#
#     [plain] chars=5    [héllo] chars=6        CPython: [plain] 5, [héllo] 5
#
# The refusal below is the safe direction for the DIRECT spelling: a call that
# passes a foreign-bytes value into a parameter the callee measures as TEXT.
# The TRANSITIVE spelling (`f(s)` calling `g(s)`) is covered by the least fixed
# point `text_measured_parameters` computes over forwarding calls, and the
# RETURNED spelling (`y = ident(x)` then `len(y)`) by
# `returned_parameter_position` carrying the foreign kind through the call
# result in `ValueKinds`. All three were measured wrong on both architectures
# before their fix, so each is pinned by a row in `test_formal_os_backing.py`
# rather than left to the message.
_CODEPOINT_MEASURED_METHODS = ("find",)


def _bare_ident_name(expr):
    """The name a bare `IdentExpr` spells, else None."""
    return expr.name if isinstance(expr, F.IdentExpr) else None


def codepoint_measured_parameters(fn) -> frozenset:
    """The parameter NAMES `fn`'s body asks a CODE POINT question about.

    `len(p)` and `p.find(...)` — the two constructs `string_codepoint_verdict` /
    `string_position_verdict` answer, where a byte answer is not CPython's. Every
    other string operation this path lowers is a property of the BYTES that
    CPython agrees with (a compare, `count`, `startswith`, `%s`, a print), so
    nothing else is collected. A nested `def`'s body is NOT descended into: its
    names are a different scope, and a same-named local there would otherwise
    refuse a call that is fine.

    A NAME rather than a parameter list, because the caller intersects this with
    the callee's parameter names — the two questions ("what does the body
    measure" and "which of those is a parameter") live in two places on purpose.
    """
    measured = set()
    for node in iter_nodes(getattr(fn, "body", None) or [],
                           skip=(("FunctionDef", "body"),)):
        if not isinstance(node, F.CallExpr):
            continue
        func = node.func
        if isinstance(func, F.IdentExpr) and func.name == "len":
            for a in (node.args or ()):
                nm = _bare_ident_name(a)
                if nm is not None:
                    measured.add(nm)
        elif isinstance(func, F.MemberExpr) \
                and func.member in _CODEPOINT_MEASURED_METHODS:
            nm = _bare_ident_name(func.obj)
            if nm is not None:
                measured.add(nm)
    return frozenset(measured)


def text_measured_parameters(functions) -> dict:
    """`{function name: parameter names measured as CODE POINTS}`, transitively.

    `codepoint_measured_parameters` is the DIRECT evidence: a `len(p)` or
    `p.find(...)` in the function's own body. A parameter that is FORWARDED to
    such a parameter of another function is the same question one call out —
    `def f(s: String) -> int: return g(s)` with `def g(s): return len(s)` — and
    the value's provenance does not change because the source took a hop.

    The answer is a LEAST FIXED POINT over the image's call graph, because that
    is what "every call that reaches a text measurement" means: direct evidence
    seeds the set, a bare parameter passed to a member of the set joins it, and
    a cycle (two functions forwarding to each other) converges rather than
    recursing. Only a BARE NAME is followed, which is the same evidence
    `parameter_kinds_by_call_site` reads for the same kind of question: an
    expression with a shape of its own (`f(g(x))`, `f(x + "a")`) is not this
    parameter reaching that call, and claiming it is would refuse programs
    whose argument the analysis never named.

    The result is an OVER-APPROXIMATION and it is deliberately in the safe
    direction: a call passing KERNEL BYTES into a parameter that is measured at
    any depth is refused (`foreign_bytes_into_text_parameter_refusal`), and the
    alternative is the wrong answer this reader exists to stop — a `strlen`
    inside the callee presented as CPython's `len(str)`, measured on both
    architectures as 6 for `héllo` where CPython answers 5.

    A function defined twice is the UNION of its definitions' evidence, which
    is the same direction: an overload the build cannot tell apart must not
    make the other one's measurement disappear.
    """
    by_name: dict = {}
    for fn in functions or ():
        name = getattr(fn, "name", None)
        if name:
            by_name.setdefault(name, []).append(fn)
    measured: set = set()          # (function name, parameter name)
    edges: set = set()             # ((caller, p), (callee, q))
    for name, defs in by_name.items():
        for fn in defs:
            measured.update((name, p) for p in codepoint_measured_parameters(fn))
            params = set(_positional_parameter_names([fn]))
            for node in iter_nodes(getattr(fn, "body", None) or [],
                                   skip=(("FunctionDef", "body"),)):
                if not isinstance(node, F.CallExpr):
                    continue
                callee = call_callee_name(node.func)
                if callee is None or callee not in by_name:
                    continue
                cnames = _positional_parameter_names(by_name[callee])
                for pname, arg in zip(cnames, list(node.args or ())):
                    if isinstance(arg, F.IdentExpr) and arg.name in params:
                        edges.add(((name, arg.name), (callee, pname)))
    changed = True
    while changed:
        changed = False
        for caller, callee in edges:
            if callee in measured and caller not in measured:
                measured.add(caller)
                changed = True
    rows: dict = {}
    for name, pname in measured:
        rows.setdefault(name, set()).add(pname)
    return {name: frozenset(params) for name, params in rows.items()}


def returned_parameter_position(fn) -> int | None:
    """The positional index of the parameter `fn` hands straight back, or None.

    The RETURNED spelling of the foreign-bytes gap is `def ident(s): return s`
    called on a kernel string: the call's answer is the very bytes that went in,
    and a `len` of the result answered 6 for `héllo` where CPython answers 5 on
    both architectures. `ValueKinds` classifies the call from the callee's
    DECLARED return type (`String`), which is the honest type and says nothing
    about provenance, so the caller's binding was a plain string.

    The question this reader answers is the one piece of evidence that settles
    it: does the callee return one of its arguments unchanged? Only the
    spelling whose answer is FORCED counts — every value-returning exit is a
    bare parameter NAME and they all name the same one. A second return of
    something else, a bare `return`, or a return of an expression is a
    different function, and this returns None rather than guessing, because a
    caller that marked such a call foreign would refuse a program whose bytes
    the source plainly replaced.

    The index is into the CALL's positional arguments, so a receiver is already
    excluded by `_positional_parameter_names` and the two tables cannot
    disagree about which argument lands on which parameter.
    """
    names = _positional_parameter_names([fn])
    if not names:
        return None
    found = set()
    returns = [node for node in iter_nodes(getattr(fn, "body", None) or [],
                                          skip=(("FunctionDef", "body"),))
               if isinstance(node, F.ReturnStmt)]
    if not returns:
        return None
    for node in returns:
        value = getattr(node, "value", None)
        if not isinstance(value, F.IdentExpr) or value.name not in names:
            return None
        found.add(value.name)
    if len(found) != 1:
        return None
    return names.index(next(iter(found)))


def foreign_bytes_into_text_parameter_refusal(fn_name, callee, args, kind_of,
                                              measured=None):
    """Why a call passing KERNEL BYTES into a text-measured parameter is refused.

    `callee` is the callee's AST, `args` the call's positional arguments and
    `kind_of(expr)` the CALLER's kind reader, so this asks the same question the
    `len` lowering asks (is the operand's kind foreign?) one node earlier — at
    the call — because inside the callee the kind is gone. Returns None when the
    callee is not measured or no foreign argument reaches a measured parameter.

    `measured` is the TRANSITIVE set of the callee's parameters, from
    `text_measured_parameters` over the whole image. It defaults to the DIRECT
    reader, which is what a caller with no function table in hand can answer;
    both emitters pass the transitive one, because `f(s)` calling `g(s)` is the
    same wrong answer one call out and a one-level walk is exactly the shape
    that let the direct spelling look "done" until the next hop was measured.
    """
    if measured is None:
        measured = codepoint_measured_parameters(callee)
    if not measured:
        return None
    names = _positional_parameter_names([callee])
    for pname, arg in zip(names, args or ()):
        if pname not in measured:
            continue
        if is_foreign_bytes_kind(kind_of(arg)):
            return (
                f"the call to {fn_name} passes {spelled(arg)}, whose bytes are "
                f"the KERNEL's, into its parameter `{pname}`, and {fn_name} "
                f"measures `{pname}` as TEXT (`len`/`find`), which is refused: "
                f"on this path it would answer in BYTES where CPython answers in "
                f"CHARACTERS. The two agree only while the text is ASCII, and a "
                f"kernel-supplied name need not be: measured on both "
                f"architectures over a directory holding `plain` and `héllo`, "
                f"`len` of an entry through a `String` parameter answered 6 "
                f"where CPython answers 5, exit 0 and nothing on stderr. Print "
                f"or compare the bytes, or take the BYTE count on purpose with "
                f"`os.str_len({spelled(arg)})`; a CHARACTER count of a kernel "
                f"string is not answerable on this path. The kind rides on the "
                f"expression that READ the kernel bytes, not on the word, so "
                f"this call is refused on the argument's PROVENANCE.")
    return None


def is_number_kind(kind) -> bool:
    """Whether a value of this kind is printed as a NUMBER.

    Two kinds, and they are two because they are different claims that happen to
    be lowered the same way: an integer is a number by definition, and a type TAG
    is a 64-bit word that `printf("%d")` prints faithfully.  The predicate exists
    so that the two backends' `print()` format switch has one answer rather than
    a tuple each — the same lesson `len_operand_lowering` carries, for the same
    reason (two private copies of a decision disagreed about what a string is).
    """
    return kind in (INT_KIND, TYPE_KIND)




# ── IEEE-754 binary64: the arithmetic, the comparisons, the conversions ────
#
# Everything a `double` needs that an integer word does not, in ONE place, read
# by both backends.  The reason it is one place and not two private tables is
# the one every other shared table in this file exists for and the one this
# subject makes sharper than most: **the two architectures' floating-point
# compare instructions report UNORDERED differently, so a per-backend choice of
# condition code is a per-backend choice of what `a < b` means when one operand
# is a NaN.**  CPython says every ordering comparison with a NaN is false and
# `!=` is true.  The integer conditions would get `>` and `>=` backwards on
# both machines, and `==` too on x86-64, and both would still BUILD.
#
# So what lives here is the DECISION, expressed in vocabulary neither backend
# spells natively, and each backend has a small map from these names to its own
# condition codes.  There is deliberately no `COND_*` constant in this table:
# `formal/x86_64.py` imports this module, so a table naming x86 condition codes
# would make the dependency run the wrong way.

#: Which operand is the compare's FIRST one.  `a > b` is not `b < a` in the
#: instruction stream, it is `FCMP b, a` followed by the same condition `a < b`
#: uses — which is the whole trick, because the unordered flags make `>` and
#: `>=` FALSE and every "unsigned greater" condition TRUE for them.
FLOAT_FIRST_OPERAND = "left"
FLOAT_SECOND_OPERAND = "right"

#: The four readings of a floating compare's flags this path needs, named for
#: what they MEAN rather than for the bit that reads them.  `LT` and `LE` are
#: the only two that are FALSE for an unordered compare on both machines — which
#: is the property that makes them the only two usable for CPython's ordering
#: comparisons, and why `==`/`!=` are not built from them.
FLOAT_LT = "less"
FLOAT_LE = "less-or-equal"
FLOAT_EQ = "equal"
FLOAT_NE = "not-equal"

#: Comparison operator -> (which operand the compare reads first, reading).
#:
#: The two rows that are not the identity are `>` and `>=`, and the reason is
#: arithmetic rather than taste.  On both machines an unordered compare sets
#: flags that read as "greater or equal" (`arm64`: `C=1`; x86-64: `CF=1`,
#: `ZF=1`, `PF=1`), so `a > b` cannot be tested by anything that means
#: "greater": it would be TRUE for a NaN, where CPython says FALSE.  Reading
#: `b` against `a` first and asking the LESS question instead makes the
#: unordered case answer false, because an unordered compare also clears the
#: sign flag both machines' `less` conditions read.
FLOAT_COMPARISONS = {
    "<": (FLOAT_FIRST_OPERAND, FLOAT_LT),
    "<=": (FLOAT_FIRST_OPERAND, FLOAT_LE),
    ">": (FLOAT_SECOND_OPERAND, FLOAT_LT),
    ">=": (FLOAT_SECOND_OPERAND, FLOAT_LE),
    "==": (FLOAT_FIRST_OPERAND, FLOAT_EQ),
    "!=": (FLOAT_FIRST_OPERAND, FLOAT_NE),
}

#: Binary operator -> the arm64/x86-64 mnemonic pair for it.  Both backends
#: consult this and each picks its own column, because `+` is `ADD` for an
#: integer and `FADD` for a double and the difference is the entire subject: the
#: integer one adds two PATTERNS, which builds and answers a different number.
#:
#: `*` and `+` are the two operators whose INTEGER reading this overrides for a
#: double, and `/` is the third; `%`, `//` and `**` are absent, which is the
#: honest answer — CPython's `7.0 % 2` is `1.0` and `7.0 // 2` is `3.0`, both
#: FLOOR operations on doubles that neither FP unit has an instruction for and
#: that this path would have to spell.  `float_binary_refusal` is what says so,
#: in the words a reader needs, instead of falling through to an integer divide
#: that computes a truncation.
FLOAT_BINARY_MNEMONICS = {
    "+": ("fadd", "addsd"),
    "-": ("fsub", "subsd"),
    "*": ("fmul", "mulsd"),
    "/": ("fdiv", "divsd"),
}


def float_binary_refusal(op: str, left_kind, right_kind, spelled_expr: str,
                         left=None, right=None) -> str | None:
    # `spelled_expr`, not `spelled`: the module-level `spelled()` reader spells
    # the two OPERANDS and this message names both of them, and a parameter that
    # shadows it is a `TypeError` in the middle of building a diagnostic —
    # measured, on both architectures, as `neg_mod` and `neg_div_rem` failing
    # with `'str' object is not callable` once `float_binary_refusal` was
    # reached from a program with no float in it at all.  The name follows
    # `string_binary_refusal`'s `spelled_op`, which is the same reason.
    """Why this binary operation is not a double operation here, or None.

    Three shapes, and the first two are MIXED operands rather than unsupported
    ones.  `1.5 + 2` has no type on this path — `infer_expr` answers
    `DEFAULT_INT_TYPE` for a `FloatLiteral` because a `FloatLiteral` has never
    reached an arithmetic instruction — and picking a side would be a silent
    wrong answer: promoting the literal would change `1e308 * 10.0` from an
    infinity to a finite number, and truncating the double would change
    `2.5 + 1` from `3.5` to `3`.  So a mixed pair is REFUSED, by name, which is
    also what Mojo does (`Int64 + Float64` is a type error there, so a program
    that reaches this is not the program its author wrote).

    The third is the operator list above reaching its end: `%`, `//`, `**` and
    the bitwise operators on a double are refused BY NAME, because the integer
    lowering of each is reachable and would compute a truncation.  `7.0 // 2`
    answered `3` as an integer divide, where CPython answers `3.0`.
    """
    if left_kind != FLOAT_KIND and right_kind != FLOAT_KIND:
        # Not a float operation AT ALL, whatever the operator.  The condition is
        # about the OPERANDS and not about `op`: it used to be guarded by
        # `op in FLOAT_BINARY_MNEMONICS`, which meant every operator outside that
        # table reached the refusal below with two integers in hand and named
        # them an integer and a double in the same sentence.  Measured on both
        # architectures as `neg_div_rem` and `neg_mod` — `a // 2` over two
        # `Int`s — failing with a message that says "one side is an IEEE double"
        # and then prints "a is an integer, 2 is an integer".
        return None
    if left_kind == FLOAT_KIND and right_kind == FLOAT_KIND:
        if op in FLOAT_BINARY_MNEMONICS:
            return None
        return (
            f"`{spelled_expr}` is an operation on two IEEE doubles "
            f"that this path does not lower: `+`, `-`, `*` and `/` are, "
            f"and `{op}` is not, "
            f"because neither floating-point unit has an instruction for it "
            f"and CPython's `{op}` on doubles is not the integer `{op}` — "
            f"`7.0 {op} 2` is a floating-point answer, not a truncated one. "
            f"Spelled as one of the four, or compute the floor explicitly.")
    where = ("one side is an IEEE double and the other is an integer"
             if (left_kind == FLOAT_KIND) != (right_kind == FLOAT_KIND)
             else "an operand is an IEEE double")
    spelled_left = spelled(left) if left is not None else "the left operand"
    spelled_right = spelled(right) if right is not None else "the right operand"
    return (
        f"`{spelled_expr}` mixes types this path does not promote: {where} "
        f"({spelled_left} is "
        f"{_float_operand_word(spelled_left, left_kind)}, {spelled_right} is "
        f"{_float_operand_word(spelled_right, right_kind)}). There is no "
        f"implicit conversion between them here — picking a side would be a "
        f"silent wrong answer, since promoting the integer rounds and "
        f"truncating the double loses the fraction. Convert explicitly: "
        f"`float(n)` for the integer, or `Int(x)` for the double.")


def _float_operand_word(spelled: str, kind) -> str:
    """`a double` / `an integer` — one reader, so the two rows cannot differ."""
    if kind == FLOAT_KIND:
        return "an IEEE double"
    return ("an integer" if kind in (INT_KIND, TYPE_KIND)
            else "a value of unestablished kind")


def float_comparison(op: str, left_kind, right_kind):
    """`(first_operand_is_left, reading)` for a double comparison, or None.

    None means "this is not a double comparison", which is the ordinary answer
    for every program with no `double` in it — so a backend asks this BEFORE
    its integer path and the integer path is untouched when it says None.
    """
    if not (left_kind == FLOAT_KIND or right_kind == FLOAT_KIND):
        return None
    if op not in FLOAT_COMPARISONS:
        return None
    first, reading = FLOAT_COMPARISONS[op]
    return (first == FLOAT_FIRST_OPERAND, reading)


def float_unary_refusal(op: str, operand_kind, spelled: str,
                        operand=None) -> str | None:
    """Why this unary operation is not a double operation here, or None.

    `-x` is the one that IS lowered, and it is worth saying why it needs its own
    instruction rather than being `0.0 - x`: that expression is `+0.0` where
    CPython's `-0.0` is `-0.0`, and the two compare EQUAL — so a differential
    test that only exercises arithmetic would pass on a negation that is wrong
    on the one value where signed zero is observable.
    """
    if operand_kind != FLOAT_KIND:
        return None
    if op == "-":
        return None
    return (
        f"`{spelled}` is a unary operation on an IEEE double that this path "
        f"does not lower: unary `-` is, and `{op}` is not, because a `double`'s "
        f"truthiness and its bitwise complement are both questions about IEEE "
        f"special values (a NaN is truthy where a nonzero integer is too, and "
        f"`~x` on a bit pattern is not what the source means). Spelled "
        f"differently, or say what the double means first.")


def float_int_conversion_note() -> str:
    """The one documented divergence from CPython in a double→int conversion.

    A double whose truncated value does not fit in an `Int64`, and an infinity
    (which is one: CPython raises `OverflowError` for both), is a trap —
    refused at build time when the source spelled it (`float_to_int_refusal`),
    checked at run time when it cannot be read (`float_to_int_trap_message`),
    and stopped with `INT_OVERFLOW_TRAP_STATUS`, which is the one answer this
    path gives for a program CPython raised.

    The remaining divergence is a NaN. `FCVTZS` and `CVTTSD2SI` SATURATE one,
    and each answers ITS OWN saturation — measured on both: `FCVTZS` converts
    a NaN to 0, `CVTTSD2SI` to `INT64_MIN` (`0x8000000000000000`) — while
    CPython raises `ValueError` for it, so the one input the range test
    cannot separate is also the one the two machines still part company on.
    The range test cannot take a NaN — it has no value to check, and both
    comparisons it is built from are false (unordered) for one — so neither
    the build's refusal nor the emitters' trap fires for it, and the trap
    must not be spent on it: this trap is the OverflowError trap, and
    attributing a stop to a range a NaN does not have would be a false
    message. That is a divergence on an input rather than an approximation of
    one, and this note is the record of it.
    """
    return ("a NaN is the one input the range test cannot separate, and each "
            "hardware answers its own saturation for it — 0 on arm64 "
            "(FCVTZS), INT64_MIN on x86-64 (CVTTSD2SI) — where CPython "
            "raises ValueError; a double whose truncated value does not fit "
            "in an Int64, and an infinity, are refused at build time when the "
            "source spells them and trapped at run time with the integer "
            "overflow's status, which is what CPython's OverflowError is on "
            "this path; every other value is exact")


#: Type constructors whose VALUE is an IEEE double — `float(x)`, `Float64(x)`.
#:
#: `float` is here for the reason `int` and `str` are in `INT_TYPE_CTORS` /
#: `IDENTITY_TYPE_CTORS`: it is a name the model compiles rather than a symbol
#: libSystem defines, and left to the extern path `float(2)` became `BL _float`
#: — an image the LINKER refused ("the image would bind 1 symbol(s) that
#: nothing provides"), which is the honest failure but not a usable one.  Both
#: spellings of the TYPE are here and `float` the PYTHON spelling, for the
#: reason `INT_TYPE_CTORS` carries both `int` and `Int`: one declaration written
#: two ways, and a table that knew one would answer differently for the two.
FLOAT_TYPE_CTORS = ("float", "Float64", "float64")

#: What a conversion between an integer and a double is called, in both
#: directions.  Named rather than inlined because both backends branch on the
#: answer and neither should be the one deciding what it means.
FLOAT_TO_INT = "from-float"
FLOAT_FROM_INT = "to-float"


def float_conversion_lowering(callee_name: str, operand_kind, spelled: str,
                              value: float = None):
    """`("from-float" | "to-float" | None, refusal)` for a conversion call.

    Two directions, and the asymmetry between them is the whole answer:

    * an INTEGER type constructor over a `double` — `Int(x)`, `int(x)` — is
      `FCVTZS`/`CVTTSD2SI`, truncating toward zero, which is CPython's rule.
    * `float(x)` / `Float64(x)` over an INTEGER is `SCVTF`/`CVTSI2SD`, and over
      a `double` is the IDENTITY — the bits are already the right ones and a
      conversion would round a value that is exactly representable, which is a
      no-op that can only lose the one input that is not (`float(nan)` stays a
      NaN either way, so the identity is safe in both directions).

    `None` with no refusal means "this is not a float conversion", which is the
    answer for every ordinary `Int(x)` over an integer and lets the integer path
    run untouched.

    `value` is the operand's value when the build can read it (a float literal,
    or one with a unary minus — `float_literal_value`), and it is asked ONLY of
    the `from-float` direction, where a double the build can read and that does
    not fit in an `Int64` is refused instead of lowered: CPython raises
    `OverflowError` for it, and the hardware would answer a saturation instead
    — `INT64_MAX` on one architecture and `INT64_MIN` on the other, which is a
    divergence the two machines used to disagree with each other on. A value
    the build cannot read is not refused here: the emitters check the same
    range at run time and stop with `INT_OVERFLOW_TRAP_STATUS`.
    """
    if callee_name in INT_TYPE_CTORS:
        if operand_kind == FLOAT_KIND:
            if value is not None and float_to_int_out_of_range(value):
                return (None, float_to_int_refusal(spelled))
            return (FLOAT_TO_INT, None)
        return (None, None)
    if callee_name not in FLOAT_TYPE_CTORS:
        return (None, None)
    if operand_kind == FLOAT_KIND:
        return (None, None)                     # the identity, per above
    if operand_kind in (INT_KIND, TYPE_KIND, None):
        return (FLOAT_FROM_INT, None)
    return (None,
            f"`{spelled}` converts a {operand_kind} to an IEEE double, and "
            f"there is no conversion from that kind to one on this path: the "
            f"only two are an integer (SCVTF) and a double (the identity). "
            f"Convert to an integer first, or say what the value is.")


#: The two doubles a double→int conversion must check against, and the reason
#: the lower one is not the smaller side of the `Int64` range itself.
#:
#: `FCVTZS`/`CVTTSD2SI` truncate toward zero, and the truncated value must fit
#: in an `Int64`: `INT64_MIN .. INT64_MAX`. The UPPER boundary is the range
#: edge — `2**63` is representable, truncates to itself, and does not fit, so
#: `x >= 2**63` is the whole upper test. The LOWER edge is not: `-2**63`
#: truncates to `INT64_MIN` and FITS, so the range's own minimum is not the
#: constant. But a double cannot name the trap: the spacing of binary64 above
#: `2**63` is 2048, so there is no double between `-2**63 - 2048` and
#: `-2**63`, and "the value does not fit below the range" over doubles is
#: exactly `x <= -2**63 - 2048`. Both boundaries are doubles, both are the
#: extreme members of the trap, and a Python `float` read of either is exact,
#: so the build-time and run-time halves compare the same two values.
FLOAT_TO_INT_HI = 2.0 ** 63
FLOAT_TO_INT_LO = -(2.0 ** 63) - 2048


def float_to_int_out_of_range(value: float) -> bool:
    """Whether a double's truncated value does not fit in an `Int64`.

    The ONE test both halves of the double→int decision mean: the build's
    refusal asks it of a literal the source spelled, and the emitters' range
    test is the same inequality over the run-time word. CPython is the
    oracle: `int()` truncates toward zero and raises `OverflowError` when
    the truncated value is past `Int64`'s range, and over the set of doubles
    that is exactly `x >= FLOAT_TO_INT_HI` or `x <= FLOAT_TO_INT_LO` (the
    boundary arithmetic is the comment on the constants above).

    An infinity answers `True`, which is right: CPython raises `OverflowError`
    for it, and the hardware would saturate. A NaN answers `False`, because
    neither comparison holds for one, and a NaN is the one input the trap
    must NOT take: it has no value to check, `FCVTZS`/`CVTTSD2SI` give it the
    hardware's saturation, and `float_int_conversion_note` records that
    divergence rather than a comparison settling it.
    """
    return value >= FLOAT_TO_INT_HI or value <= FLOAT_TO_INT_LO


def float_literal_value(e):
    """The value of a float literal, or of one with a unary `+`/`-`, else None.

    The one reader of "can the build read a double", for both backends, for
    the reason `integer_literal_value` exists: a rule that read the literal
    with one backend's private spelling is a rule that misses the other
    spelling. `Int(1e300)` and `Int(-1e300)` are the two shapes the parser
    keeps — the minus is a node (`UnaryOp('-', FloatLiteral)`) rather than a
    sign on the literal — and a `0 - 1e300` is a `BinaryOp`, which no build
    can fold here, so it is None and the run-time range test answers it.
    """
    if isinstance(e, F.FloatLiteral):
        return e.value
    if isinstance(e, F.UnaryOp) and e.op in ("-", "+"):
        v = float_literal_value(e.operand)
        if v is not None:
            return -v if e.op == "-" else v
    return None


def float_to_int_refusal(spelled: str) -> str:
    """The build-time half of the double→int range decision.

    Asked from `float_conversion_lowering` when the build can read the operand
    and `float_to_int_out_of_range` says it does not fit: the source spelled a
    value, so the answer CPython gives — an `OverflowError`, the program's own
    next line never reached — is knowable at build time, and the honest move
    is to say so rather than lower a conversion the hardware would answer with
    a saturation. The saturation is not one wrong answer: `FCVTZS` clamps at
    `INT64_MAX` and `CVTTSD2SI` at `INT64_MIN`, so the two architectures used
    to answer the same source with two different programs, which is the
    divergence this refusal closes at the place it is decidable. A value the
    build cannot read is not refused and is checked at run time instead —
    `float_to_int_trap_message` is that half, and `INT_OVERFLOW_TRAP_STATUS`
    is the one status both leave behind.
    """
    return (f"{spelled} converts a double whose value the build can read, and "
            f"it does not fit in an Int64: CPython raises OverflowError for "
            f"an `int()` past the 64-bit range, and the hardware's "
            f"FCVTZS/CVTTSD2SI would answer a saturation instead — "
            f"{INT64_MAX} on one architecture and {INT64_MIN} on the other — "
            f"so this build refuses rather than emit the answer the hardware "
            f"would give. A value the build cannot read (a name, a parameter, "
            f"a field) is not refused here: it is checked at run time, and an "
            f"out-of-range one stops the program with the integer overflow's "
            f"status.")


def float_to_int_trap_message() -> str:
    """The ONE text a double→int conversion past the range writes to fd 2.

    For BOTH backends, in the shape of `int_overflow_trap_message`: the three
    things a reader needs and no more — what the target cannot do, what
    CPython would have said, and that this is a stop rather than an answer.
    The status it is written for is `INT_OVERFLOW_TRAP_STATUS`, because "this
    program could not be answered on this target" is one answer on this path,
    and a reader who has seen an overflow stop should not have to learn that a
    conversion stops differently.
    """
    return ("OverflowError: this program converted a double to an integer, "
            f"and the double's truncated value does not fit in the signed "
            f"64-bit range this target has for an integer ({INT64_MIN} .. "
            f"{INT64_MAX}). CPython raises OverflowError for that program; "
            "this formal image has no way to raise, so it stops here rather "
            "than answer the hardware's saturation (which is a different "
            "number on each architecture).\n")


def float_literal_bits(value) -> int:
    """The 64-bit IEEE-754 binary64 pattern of a Python float, as an unsigned int.

    The one reader of a literal's bits, for both backends, because a literal
    reaches the FP unit as an ordinary 64-bit immediate (`MOVZ`/`MOVK` on arm64,
    `MOVABS` on x86-64) and the two must not disagree about which pattern a
    source literal denotes.  `struct.pack` is the oracle rather than a hand
    layout for the same reason the encoders are checked against an assembler:
    it is the platform's own conversion.

    A literal `int` or `bool` is accepted so a caller need not re-test, and
    because CPython's `float(2)` is `2.0` — so a source that writes `2.0` in a
    shape that has already been folded to an integer is asking for the same
    number.
    """
    import struct as _struct
    if isinstance(value, bool):
        value = float(value)
    elif isinstance(value, int):
        value = float(value)
    elif not isinstance(value, float):
        raise ValueError(f"{value!r} is not a float literal")
    # A Python float is C double, so this packs exactly the 64 bits a `double`
    # is.  Overflow is `struct.error`, which is a compiler crash rather than a
    # refusal — so the finite range is checked here, where it can be a message.
    # `inf` and `nan` pack without complaint and are values the format has to
    # carry: `0.0 / 0.0` is a NaN on both architectures and `printf("%f", ...)`
    # prints it, so refusing them here would refuse a RESULT rather than a
    # literal anybody wrote.
    return int.from_bytes(_struct.pack(">d", value), "big")




# ── Calls that are not calls to a symbol ──────────────────────────────────
#
# The default lowering of a call is a BL against a symbol spelled the way the
# source spelled it. That is right for a MODULE call (`os.path.join`, an
# imported function, a linked dylib's export) and wrong for two other things,
# both of which used to produce an image that built cleanly and then died in
# dyld with "Symbol not found" — the failure mode that is worst in a compiler,
# because everything upstream of it reports success:
#
#   * a BUILTIN whose name libSystem does not define. `print` is the one that
#     matters: it is in every hello-world-shaped file, it is not a C symbol,
#     and left to the extern path it became `BL _print`.
#   * a method call on a plain VALUE. `items.append(x)` is not a call to a
#     symbol spelled `items.append`; the receiver's VALUE picks the meaning,
#     and the receiver itself is the first argument.
#
# What each of those MEANS is a model decision, so it is here; which
# instructions implement it is the backend's.

# The methods this model can lower on a value, and what each one lowers to.
# A method NOT in this table is refused by the backend rather than guessed at:
# `elem.copy()` has no meaning without knowing what `elem` holds, and picking
# one would be a plausible-looking wrong answer behind a clean build.
#
# Membership here is NECESSARY but not SUFFICIENT: a name in it is only lowered
# when the receiver's kind is also established (see value_method_refusal), so
# adding a name here without a kind guard would lower `x.value()` on a
# non-string x as a string operation.
BUILTIN_VALUE_METHODS = {
    # `list.append(x)`: store x at count and bump the count. There is no heap
    # on this path, so the blob's capacity is a compile-time bound — the count
    # of append sites in the function — and the store is checked against it.
    "append": "list_append",
    # `list.clear()`: the count word is the blob's header, so emptying a list is
    # ONE store of zero at offset 0 of it. `std/collections/binary_heap.mojo`'s
    # `clear`, and it is the whole of that method:
    #
    #     def clear(mut self):
    #         self._data.clear()
    #
    # It is in this table and not in a backend's own because the two
    # architectures would otherwise have two `clear` lowerings that can agree
    # today and drift, and because the KIND GUARD is a model decision —
    # `append`'s guard is capacity and lives in the emitter, which is the reason
    # that arm says why its own does not. And the guard is POSITIVE evidence
    # (`is_list_kind` of the receiver's kind) rather than the absence of a
    # refusal, because a name in this table with no kind guard would zero the
    # first word of ANY word and leave the program running.
    "clear": "list_clear",
    # `f.write(s)`: a text-mode write of a C string to a file descriptor.
    # `open(...)` already lowers to the C library's `open`, so the receiver
    # IS a descriptor and this is `write(fd, s, strlen(s))`.
    "write": "file_write",
    # `f.close()`: the C library's `close` on the same descriptor.
    "close": "file_close",
}

#: The receiver kind a `BUILTIN_VALUE_METHODS` entry REQUIRES, for the ones
#: whose guard is a kind rather than a fact an emitter has. One table and one
#: reader (`_shape_guarded_refusal`) rather than a branch per method, and it is
#: empty for `append`/`write`/`close` because their guards are CAPACITY and
#: FILE-DESCRIPTOR-ness respectively — `append`'s emitter guard and
#: `VALUE_METHOD_RECEIVERS`'s. `clear` is the case that needs one: storing zero
#: at offset 0 of a word that is not a blob's header writes zero into whatever
#: address that word holds, so it is honest only on a receiver established to be
#: a list.
BUILTIN_VALUE_METHOD_LIST_KINDS = frozenset({"clear"})


# `xs.clear()` on a receiver this path has not established to be a blob.  Shared
# by both backends for the reason `list_append_overflow_message` is: two
# architectures that name one limit differently cost a reader the difference
# between the limit and the architecture.
def list_clear_refusal(dotted: str, kind, shape: str) -> str:
    """Why `dotted.clear()` is not lowered here.

    The guard is `is_list_kind`, and a DICT passes it — deliberately, and by
    measurement rather than by accident: a dict on this path is a counted blob
    too (`len_operand_lowering` reads its count from the same offset 0), so
    zeroing that word empties it exactly as CPython's `dict.clear` does.
    Measured on both architectures, `{"a": 1, "b": 2}` reports 2, clears to 0,
    and a SECOND dict built after the clear still reports 1 — the third number
    is the one that makes the store a store rather than a coincidence.
    `test_formal_run.py::list_clear_empties_a_dict_blob` is that row.

    **Asked from `_shape_guarded_refusal`, once, for both architectures** — the
    `BUILTIN_VALUE_METHOD_LIST_KINDS` arm above is the guard, and each backend's
    `_emit_value_method` asks `value_method_refusal` (hence this) with
    `_method_recv_kind(e)` before it dispatches, so an emitter-level copy of the
    same `is_list_kind` question would be the second reader of a fact the first
    one already settled with the same arguments.  The sentence carries both
    halves of the argument: what the store IS (one word, at the offset a
    container's count lives at, which is the word `len` reads), and what it
    would do to a word that is not a blob's header.
    """
    return (f"{dotted}() lowers to one store of zero at offset 0 of its "
            f"receiver, and that offset is a container's COUNT — the very word "
            f"`len` of the same receiver reads — so the store empties a list "
            f"and writes into whatever address anything else holds, and "
            f"the receiver has to be a list. {dotted}'s is "
            f"{shape or 'a plain word'} classified as "
            f"{kind if kind is not None else 'nothing this path can establish'}"
            f", and this path will not read an arbitrary word as a blob's "
            f"header. Cleared anyway it would zero the first eight bytes of "
            f"whatever the word holds, and the program would keep running with "
            f"a wrong length: that is the silent wrong answer this path does "
            f"not emit. Bind a list to a name and call the method on the name, "
            f"or give the field a `List[…]` declaration so the receiver's kind "
            f"is stated")




# ── Methods on a string ───────────────────────────────────────────────────
#
# A string on this path is a bare `char *` with no header and no length: see
# the note on ValueKinds below, and the 2026-09 x86-64 backend-gap survey
# (deleted with its fixes; `len` of a *string* is the case it named) for why
# that also makes `len` of a string a real question rather than a field load. That single fact SPLITS the string methods into two classes, and
# which side a method falls on decides whether it can be lowered at all:
#
#   POINTER-BOUNDED — the answer is a function of the bytes from the receiver
#   to the NUL, computable by walking the buffer. `strstr`/`strncmp`/`strcspn`
#   are exactly these algorithms and libSystem has all three, so the lowering
#   is a call, not a hand-written scan that could be subtly wrong.
#
#   LENGTH-DEPENDENT — the answer needs a LENGTH first, and a length on a bare
#   `char *` is only available by scanning to the NUL. Where that is the whole
#   of the work (`len`) it is still pointer-bounded, because `strlen` computes
#   it exactly. Where the length is needed to decide WHERE THE RESULT ENDS, the
#   result has to be a buffer of its own, and this path has nowhere to put one:
#   there is no heap, and the receiver's own bytes are not available as a
#   scratch area (see the strip note below).
#
# The refusal is per-NAME and says which half of that is missing, because the
# two are not interchangeable arguments: a reader who wants `split` has to
# change the string REPRESENTATION, and a reader who wants `strip` needs only
# a place to copy into.

# What each lowered string method does, and what it yields. The yield is what
# the classifier needs so that `m = s.lstrip()` binds `m` as a string and the
# NEXT method call on it is not refused for want of a kind. This is the
# `_expr_str_kind` lesson one level up: a method whose result is misclassified
# poisons every use site after it, and the symptom is a wrong answer rather
# than a diagnostic — `print(m)` prints a pointer as a number, and `m == "x"`
# compares a pointer against an integer.
POINTER_BOUNDED_METHODS = {
    # An INTERIOR pointer: the bytes from the first non-whitespace character to
    # the existing NUL are exactly the answer, still in place, and nothing is
    # written. That is what makes this one pointer-bounded and `strip` not —
    # see the strip entry in LENGTH_DEPENDENT_METHODS, which is the measured
    # reason rather than a guess.
    "lstrip": ("str_lstrip", STR_KIND),
    # `strncmp(s, p, strlen(p)) == 0` — a bounded compare, since strncmp stops
    # at the first difference or at a NUL in either operand. An empty prefix
    # is a zero-length compare, which is 0, which is "yes" as Python has it.
    "startswith": ("str_startswith", INT_KIND),
    # The same compare from the far end, but only after establishing that the
    # suffix is not longer than the receiver; without that guard the pointer
    # `s + len(s) - len(p)` is computed from an unsigned underflow and the
    # compare reads outside the buffer.
    "endswith": ("str_endswith", INT_KIND),
    # `strstr` walks to the NUL of both operands, so the index of the first
    # occurrence is exactly `strstr(s, p) - s`. An empty needle is the whole
    # receiver's start, i.e. 0, which is what Python returns.
    "find": ("str_find", INT_KIND),
    # Non-overlapping, as Python's is: each match advances the cursor by the
    # needle's length, so "aaa".count("aa") is 1 and not 2. The empty needle
    # is the one case with no loop — it matches at every position, so the
    # answer is the receiver's length.
    "count": ("str_count", INT_KIND),
}

# The ASCII whitespace set, shared by the two backends so a trim cannot mean
# one thing on arm64 and another on x86-64. 0x20 is the space; 0x09..0x0D are
# tab/LF/VT/FF/CR. As a predicate over a byte B:
#     B == 0x20  or  0x09 <= B <= 0x0D
# NUL is deliberately NOT in the set: the terminator is what ends the string,
# and trimming it would walk off the end of the buffer.
STRIP_MAX = 0x20
STRIP_LO = 0x09
STRIP_HI = 0x0D

# The same set as the ACCEPT SET of `strspn`, which is how both backends
# actually compute `lstrip`: `s + strspn(s, STRIP_CHARS)` IS the left-strip,
# because strspn returns the length of the initial segment consisting only of
# characters from that set.
#
# This is not a shortcut, it is the correction. The first version of this was a
# hand-written byte loop in each backend, and TWO bugs lived in it that neither
# shared: the arm64 copy lost the `cmp` that sets the flags its final `b.eq`
# tests, so it silently failed to trim the space — the one character the method
# is named after — while still trimming tabs; and the x86-64 copy was
# correct-looking code that did not run. One libc call is the same algorithm
# Python uses, it cannot be half-right, and there is now nothing here to keep in
# step between two architectures. A second implementation of a libc routine is
# a second thing to be wrong.
#
# The control characters are REAL bytes here, which is the point: this is a
# Python-level constant, not a Mojo string literal, so the unescaping question
# (does "\t" in the source mean a tab or a backslash and a t?) does not arise.
# STRIP_CHARS is a superset test in strspn, so a NUL in it would be a bug —
# it is not, and there is an assertion below.
STRIP_CHARS = " \t\n\v\f\r"
assert len(STRIP_CHARS) == 6, "the whitespace set changed shape"
assert "\0" not in STRIP_CHARS, "NUL must not be trimmable"
assert STRIP_CHARS[0] == chr(STRIP_MAX)
assert all(STRIP_LO <= ord(c) <= STRIP_HI for c in STRIP_CHARS[1:])

# Methods that are REAL string methods and are still refused, with the reason
# each one is out of reach. Keyed by name; the value is the missing half of the
# argument, quoted in the diagnostic.
#
# The two CODEPOINT reasons are written ONCE and shared by the fifteen names
# that are missing the same half, for the reason every other message in this
# file is written once: fifteen near-copies of one sentence is fifteen things
# to fall out of step, and a reader who has read one has read them all. They
# are named here rather than inlined into the table so that the table below
# stays a table of NAMES — which is what a reader scans — and so the shared
# text has a docstring of its own explaining why the family is a family.
#
# `CODEPOINT_CLASS_REFUSAL` and `CODEPOINT_CODEC_REFUSAL` are the two halves of
# the same missing thing and are kept apart because they name different
# questions: a predicate asks "what KIND of character is this one" and a codec
# asks "what code point does this one stand for", and a reader who wants
# `isalpha` and a reader who wants `decode` are blocked by different parts of
# the same gap.
CODEPOINT_CLASS_REFUSAL = (
    "asks whether each CHARACTER of the receiver belongs to a class, and the "
    "answer is a property of a CODE POINT rather than of a byte — `\"²\".isdigit()` "
    "is true, and there is no way to read that off a `char *` holding its three "
    "UTF-8 bytes. A byte predicate would be a DIFFERENT predicate rather than a "
    "wrong one this path can honestly emit, and it would be wrong exactly where "
    "the text is non-ASCII, which is silently")
CODEPOINT_CODEC_REFUSAL = (
    "maps CODE POINTS to bytes or bytes to code points, and the half of that a "
    "bare `char *` already has is the bytes — the code point is what is missing, "
    "and a UTF-8 byte is not one (`\"é\"` is two bytes and one character, "
    "`\"日本\"` is six bytes and two)")

LENGTH_DEPENDENT_METHODS = {
    # The one that is NOT about length, and the clearest statement of what is
    # actually missing. `strip` is a one-character edit away from `lstrip`:
    # both find the first non-whitespace byte. The difference is what happens
    # at the FAR end, and it is not a computation but a WRITE — a shorter
    # string has to be terminated one byte earlier, and on a bare `char *` the
    # only byte there to write is the receiver's own.
    #
    # Measured, not assumed. String literals are interned by content and
    # emitted after the code into `__TEXT,__text` (`_intern_string` in either
    # backend), and that segment is mapped `maxprot 0x5` — read and execute,
    # NO write — so writing the terminator over a literal's trailing space
    # faults. And for a receiver that is not a literal, the bytes are shared
    # with every other reference to the same interned string, so the write
    # would be visible through all of them.
    #
    # An earlier version of this lowering computed the new end pointer and
    # returned it without writing anything. It built, ran, and was WRONG:
    # "   hi   ".strip() returned a pointer to a byte that still held a space,
    # so the result printed as "   " — a plausible-looking string that is not
    # the answer. That is the outcome this table exists to prevent.
    "strip": "returns a SHORTER string, which on a bare char * means writing "
             "a terminator over the first trailing whitespace byte — and the "
             "receiver's bytes cannot be written: a string literal is interned "
             "into __TEXT,__text, which is mapped read+execute and not "
             "writable, and a non-literal receiver shares its bytes with every "
             "other reference to the same interned string. lstrip() needs no "
             "write and IS lowered",
    "rstrip": "returns a SHORTER string and so needs the terminator write that "
              "strip cannot do; see strip. lstrip() is the lowered half",
    "upper": "returns a NEW string of the same length, and the only buffer "
             "available for it is the receiver's own bytes — which live in "
             "the image's text section and are interned by content, so "
             "rewriting them in place would fault and would also change "
             "every other reference to the same literal",
    "lower": "returns a NEW string of the same length; see upper",
    "swapcase": "returns a NEW string of the same length; see upper",
    "capitalize": "returns a NEW string; see upper",
    "title": "returns a NEW string; see upper",
    "casefold": "returns a NEW string; see upper",
    "replace": "has to find every occurrence of the old text and lay the new "
               "text down between them, so the RESULT's length is not the "
               "receiver's and no buffer of the right size exists",
    "join": "has to allocate one buffer sized by walking the sequence and "
            "measuring every element, and there is no heap to allocate it in",
    "split": "returns a SEQUENCE of strings, and a sequence on this path is a "
             "frame-allocated blob whose capacity has to be a compile-time "
             "bound (the count of append sites) — a split's element count is "
             "only known at run time, so there is no capacity to give it",
    "rsplit": "returns a SEQUENCE of strings; see split",
    "splitlines": "returns a SEQUENCE of strings; see split",
    "partition": "returns a SEQUENCE of strings; see split",
    "rpartition": "returns a SEQUENCE of strings; see split",
    "index": "is a length-dependent SEARCH whose result is a position, which "
             "find already answers — use find, which is lowered",
    "rfind": "walks the buffer backwards from its NUL, which needs the length "
             "first; find is the lowered direction",
    "center": "pads to a width, so it allocates a new buffer; see upper",
    "ljust": "pads to a width, so it allocates a new buffer; see upper",
    "rjust": "pads to a width, so it allocates a new buffer; see upper",
    "zfill": "pads to a width, so it allocates a new buffer; see upper",
    "format": "its result's length is a function of the format AND the "
              "operands, so it is a fresh buffer of a size nothing knows at "
              "compile time; see upper",
    # `format_map` is `format` with the mapping already resolved, so the two
    # are missing the same half and are named together rather than leaving one
    # of them to fall through to the generic sentence — which is what happened,
    # and `test_formal_str_methods.py`'s refusal group is what found it.
    "format_map": "is format() with the mapping already resolved, so its "
                  "result's length is a function of the format AND the "
                  "operands and there is no buffer of a size nothing knows at "
                  "compile time; see format",
    "removeprefix": "returns a new string whenever the prefix is present, "
                    "which is a different pointer every time; a method that "
                    "sometimes aliases its receiver and sometimes does not is "
                    "worse than a refusal",
    "removesuffix": "returns a new string whenever the suffix is present, "
                    "which is a different pointer every time; see "
                    "removeprefix",
    "reverse": "returns a NEW string, and writing into the receiver's own "
               "bytes would fault (see upper)",
    "__len__": "is len(), which IS lowered for a string — as strlen, not as a "
               "field read. Call len(s), which reads better and is the "
               "spelling both backends agree on",


    # ── the CHARACTER-CLASS and CODEC names ─────────────────────────────────
    #
    # These fifteen were in NEITHER table, so every one of them fell through to
    # `_shape_guarded_refusal` and got its sentence from there — which does not
    # name them and which sends the reader to the wrong remedy. Measured, both
    # architectures, from a green build:
    #
    #     "ab".isalpha()  ->  build: isalpha() is a method call on a value, and
    #     this backend lowers only append, clear, close, write (on a file
    #     descriptor) and the string methods count, endswith, find, lstrip,
    #     startswith — the receiver is a string literal on this path, and
    #     'isalpha' is not one of those methods of those receivers, so adding
    #     it to either table would be a guess about what it means on 'str'.
    #
    # Every clause of that is true and it is still the wrong message, twice
    # over. It is wrong about the FACT: `isalpha` IS a method of `str`, and
    # `is_string_method`'s own docstring says a name in neither table is
    # precisely the case this path cannot yet describe — so the honest
    # statement is that it belongs in one of them, not that it is "not one of
    # those methods of those receivers". And it is wrong about the REMEDY: the
    # sentence it ends with is about a length-prefixed string representation,
    # which is not what `isalpha` is waiting for.
    #
    # What they are waiting for is a CHARACTER, and this path holds BYTES. So
    # they are here, one reason for the whole family rather than fifteen
    # near-copies, and the reason says the actual missing half. It is not a
    # buffer question — a buffer would not help — and it is not a length
    # question either: `"²".isdigit()` is True in CPython and there is no way
    # to read that off a `char *`, because "²" is three bytes of UTF-8 and the
    # answer is a property of the code point 178. Naming them is what lets
    # `test_formal_str_methods.py` assert that the message carries "characters"
    # for each of them, which is the anti-rot half: a name that leaves this
    # table gets its message back, and the row that pinned it fails.
    #
    # The family is spelled out by name rather than matched by prefix on
    # purpose. A prefix rule would also catch `island` if a struct ever grew
    # one, and a refusal that fires on a name that is not a `str` method is
    # its own class of wrong message.
    "isalnum": CODEPOINT_CLASS_REFUSAL,
    "isalpha": CODEPOINT_CLASS_REFUSAL,
    "isascii": CODEPOINT_CLASS_REFUSAL,
    "isdecimal": CODEPOINT_CLASS_REFUSAL,
    "isdigit": CODEPOINT_CLASS_REFUSAL,
    "isidentifier": CODEPOINT_CLASS_REFUSAL,
    "islower": CODEPOINT_CLASS_REFUSAL,
    "isnumeric": CODEPOINT_CLASS_REFUSAL,
    "isprintable": CODEPOINT_CLASS_REFUSAL,
    "isspace": CODEPOINT_CLASS_REFUSAL,
    "istitle": CODEPOINT_CLASS_REFUSAL,
    "isupper": CODEPOINT_CLASS_REFUSAL,
    # `encode`/`decode` are the same missing half from the other direction: a
    # codec maps CODE POINTS to bytes and bytes to code points, and the half
    # of that a bare `char *` has is the bytes. `decode` in particular is the
    # tempting one — `"ab".decode()` is an identity on ASCII — and it is
    # refused anyway, because on the one input where it is an identity it is
    # also a no-op that changes nothing, and on every other input it is a
    # UTF-8 VALIDITY QUESTION that bytes can answer only by rejecting, which is
    # not what `decode` does.
    "encode": CODEPOINT_CODEC_REFUSAL,
    "decode": CODEPOINT_CODEC_REFUSAL,
    # `translate` is a table applied by CODE POINT, and `maketrans` is the
    # table's constructor, so it is missing the same half: a table keyed by
    # code point is a table keyed by integers, and this path's `str` is a
    # `char *`.
    "translate": CODEPOINT_CODEC_REFUSAL,
    "maketrans": CODEPOINT_CODEC_REFUSAL,
    # `expandtabs` is here rather than with the buffer family because it is
    # BOTH: it replaces each tab with spaces to the next multiple of
    # `tabsize`, so the result's length is not the receiver's — the same
    # missing buffer as `upper` — and it also decides column positions, which
    # is a character question on text that is not ASCII. The buffer half is
    # named because it is the one that bites first.
    "expandtabs": "replaces each tab with spaces to the next tab stop, so the "
                  "RESULT's length is not the receiver's and no buffer of the "
                  "right size exists; see upper",
    # `rindex` is `index`'s mirror and `index`'s entry below already sends the
    # reader to `find`, which is lowered. Both spellings are named so neither
    # is the one that falls through to the generic sentence.
    "rindex": "is a length-dependent SEARCH whose result is a position, which "
              "find already answers — use find, which is lowered",
}



# ── THE STRING REPRESENTATION, and why it is a bare `char *` ──────────────
#
# Wave 3 asked the same question of a multi-field struct and answered it
# BY REFERENCE: a pointer is one word, so a struct that does not fit in a word
# is reached through a pointer rather than widened. The same question has to be
# asked here, and the answer is the same shape — but it is worth being precise
# about WHY, because the two reasons are different and only one of them
# generalises.
#
# For a struct, by-reference was the only option: the fields have to live
# somewhere, and a word is all a value is. For a string, by-reference is
# available AND SUFFICIENT, because the representation is already a reference
# and the thing it refers to is not a frame:
#
#   1. A string on this path is a bare `char *` into the image's own text. The
#      bytes are interned by content (`_intern_string` in either backend) and
#      emitted into `__TEXT,__text`, which is mapped `initprot 0x5` — read and
#      execute, no write. Measured on a built image, not assumed:
#
#         SEG __TEXT  maxprot=0x5 initprot=0x5
#            __TEXT,__text addr=0x100000320 size=139
#         ... the last bytes of __text: b'hello\x00len=%d\\n\x00'
#
#      So a string is NUL-TERMINATED and the terminator is there. That one fact
#      is what makes the next point possible, and it is worth separating from
#      the rest: it is a property of the C representation, not of this backend.
#
#   2. Therefore the length is a COMPUTATION, not a FIELD. `strlen(s)` is the
#      length of a NUL-terminated `char *` by definition, so the missing length
#      costs one libc call and no storage, no second word, and no lifetime. The
#      same argument makes `==` a computation: `strcmp(a, b) == 0` is the
#      content equality of two NUL-terminated `char *`s. Both symbols are
#      ALREADY emitted by both backends — `endswith`, `count` and `f.write(s)`
#      all call `strlen`, and nothing here is new machinery.
#
#   3. A string is also the ONE pointer on this path with no lifetime problem.
#      Every string value is either a literal's bytes or an interior pointer
#      into them (`lstrip` is the only method that yields a string, and it
#      yields `s + strspn(...)`), so every string value has STATIC storage
#      duration: it is as safe to return from the function that made it, to
#      store in a container, or to hand to a callee as a frame address is not.
#      Measured, both backends, on a program that does exactly that:
#
#          def make():
#              s = "  hi".lstrip()
#              return s
#          def main(n):
#              printf("[%s]\n", make())      # -> [hi]
#
#   Point 3 is the load-bearing one for the representation question, and it
#   cuts the OTHER way from what a descriptor would want. A `{ptr, len}`
#   descriptor would put the length in a field, which means the descriptor has
#   to live somewhere: a frame (and then it inherits the frame's lifetime, so
#   every `lstrip` result would have to be refused for the same reason a struct
#   frame address is, LOSING the one string method that works today) or a heap
#   (and there is none). It would also not survive `lstrip`, which produces an
#   interior pointer with no descriptor of its own. So the descriptor is not a
#   cheaper answer — on this path it is strictly more expensive, and it buys
#   back nothing that `strlen` was not already giving.
#
# THE COST, stated rather than hidden:
#
#   * `len(s)` and `s == t` are O(n) where interning made `==` O(1) between two
#     literals. On a backend whose job is to be trustworthy rather than fast,
#     that is the right trade, and it is still a trade.
#   * A string value here CANNOT CONTAIN A NUL, because the NUL ends it. A
#     real Mojo `String` can, and `len` of a string with an embedded NUL would
#     be wrong. Nothing lowered today can produce one — every string is a
#     literal or an interior pointer into a literal — so this is a latent gap,
#     not a live wrong answer, and it is recorded here so that whoever adds the
#     first method that can build a string at run time inherits the obligation.
#   * Equality by CONTENT costs a call, and `is` / `is not` (identity) must
#     therefore NOT be lowered as `strcmp`: they are the one string comparison
#     that genuinely wants the pointer. See STRING_IDENTITY_OPS.
#
# And the cost that is NOT paid, which is the whole point: no value on this
# path gets wider, so nothing above this line has to be re-derived by anything
# that reasons about word-sized values — the struct refusal, the frame slot
# tables, the one-word field map, the call ABI, and all ~40 passing proofs.
#
# What this decision does NOT settle, and is the actual blocker in the stdlib:
# the name `String` denotes TWO different things, and only one of them is the
# representation described here. `std/collections/string/string.mojo` declares
#
#     struct String:
#         var _ptr_or_data: Pointer[UInt8]
#         var _len_or_data: Int
#         var _capacity_or_data: Int
#
# — three fields, so wave 3's by-reference receiver makes a `String` local the
# ADDRESS of a three-slot frame (verified: `struct_is_framed(String)` is True,
# `struct_frame_slots` is 3), and the frame-lifetime rule then refuses to let
# one be returned or passed on. That is where all 16 of the "a String receiver
# is returned/passed" refusals in the stdlib sweep come from, and it is NOT a
# consequence of anything above: the same program with the string kept as a
# `char *` builds and runs on both backends. Note that the length is RIGHT
# THERE, in slot 1 — so "a string needs a length" is not the problem these 16
# files have; they have a length and cannot keep it. See
# bugs/formal/FORMAL_string_value_model.md, which records the decision, the cost, and
# the two representations' collision.

# The two libc symbols this representation makes available, named once so a
# backend cannot spell one of them two ways and so the docstring above has
# something concrete to point at.
#
# The comparison is `strncmp` and NOT `strcmp`, and the reason is measured
# rather than aesthetic. `strcmp(a, b) == 0` is the obvious spelling and it
# works on arm64 — but on x86-64 an image whose only `strcmp` call sites were
# the ones this lowering emitted returned FALSE for `"abc" == "abc"`, with the
# emitted code, the interned addresses, the `__TEXT,__stubs` entry and the
# `__DATA_CONST,__got` slot all verified correct by hand. A new libc symbol on
# the x86-64 extern path is therefore not something to introduce casually, and
# the fix that is verifiable on both architectures uses the two symbols the
# backends ALREADY call for `startswith` and `f.write(s)`:
#
#     strncmp(a, b, strlen(b) + 1) == 0
#
# which is exactly `a == b` for NUL-terminated strings — comparing one byte
# past `b`'s last character means the compare cannot succeed unless it also
# compared `b`'s NUL, so it cannot succeed unless `a` ends there too. One extra
# `strlen` and one extra `add`, no new symbol, and both halves are the same
# libc calls the same two backends already make. See
# bugs/formal/FORMAL_string_value_model.md for the x86-64 observation and what it does
# and does not establish.
STRING_LENGTH_SYMBOL = "strlen"
STRING_COMPARE_SYMBOL = "strncmp"

# How `len(x)` lowers, by the kind of `x`. The two that CAN be lowered are the
# two representations that carry the count somewhere findable: a blob in a
# field at offset 0, a string as a computation over its bytes. Everything else
# is None, and None is a REFUSAL — see `len_refusal`.
LEN_FROM_BLOB_FIELD = "blob_count_field"
LEN_FROM_STRLEN = "strlen"
# The THIRD length lowering, and the only one that is not a machine operation:
# when the build KNOWS the operand's text, the number of code points in it is
# `len()` of that text, folded here and materialised as an immediate. It is the
# answer for every string whose bytes are known and no answer at all for the
# ones whose bytes are not, which is why `len_operand_lowering` below cannot
# return it on the KIND alone — see `string_codepoint_verdict`.
LEN_FROM_CODPOINT_FOLD = "codepoint_fold"
# The same three-way split for a POSITION rather than a length, and it is
# `string_position_verdict`'s rather than this table's because the question has
# two operands. See that function for why one of them is enough.
STRING_POSITION_STRLEN = "strstr_offset"
STRING_POSITION_FOLD = "codepoint_offset_fold"

# `is` / `is not` on two strings. The one string comparison that wants the
# POINTER and not the bytes, and the reason the content comparison above cannot
# be applied to it: `a is b` asks whether two names hold the same object, and
# with interning by content two equal literals ARE the same object, so the
# pointer compare is the answer rather than an approximation of it. Lowering
# `is` as `strcmp` would make `"ab" is "ab"` true for the right reason and
# `x is y` true whenever the contents match, which is a different question with
# the same spelling. Left unlowered, and refused by `string_comparison_refusal`
# with that said.
STRING_IDENTITY_OPS = ("is", "is not")

# The two answers a string comparison can have. Content is `strcmp(a, b) == 0`;
# identity is the pointer compare, which is what `is` asks for.
STRING_COMPARE_CONTENT = "content"
STRING_COMPARE_IDENTITY = "identity"


def len_operand_lowering(kind, expr=None) -> str | None:
    """How `len(x)` lowers for an operand of kind `kind`, or None to refuse.

    Shared by both backends, and the sharing is the point: the two
    architectures had one shared table deciding WHICH string methods exist and
    two private copies of the `len` decision, and the private copies disagreed
    with each other about what a string is — arm64 refused a string literal and
    read a count field for a local, x86-64 did the same, and neither asked what
    the local actually held. One table, one answer.

    `kind` is what the classifier says, and `None` means the source does not
    say. None is the case this function exists for: the old lowering read eight
    bytes at offset 0 of an unclassified word and called the result a length,
    which for a `char *` is the first eight CHARACTERS of the string. Measured
    on both architectures, `len(m)` where `m = "hello"` returned 1819043176 —
    which is 0x6C6C6568, the bytes `hell` read little-endian, and for
    `"  hi".lstrip()` it returned 536897896, which is 0x20006869, `hi` plus the
    two spaces that were trimmed. Both BUILT, both RAN, both were wrong, and
    the wrong number was indistinguishable from a right one. So the
    unclassified case is refused rather than guessed, and the refusal names it.

    `expr` is the operand node, for the shapes whose count is a fact about the
    LOWERING rather than about the kind. `range(...)` is the one that exists
    today: both backends materialise it as a `[count][elements]` blob
    (`_emit_range_list`), so its length is that blob's count field — but
    `_kind_of_call` still classifies a `range(...)` call as an integer, so the
    kind alone refuses a `len(range(10))` that has always worked and is
    covered by `len_range` in test_formal_run.py. Recognising it here, by the
    shape that decides the answer, is the honest form: the answer does not
    depend on the kind being right, it depends on what the range lowers to.

    That inconsistency is left in place rather than papered over on both sides:
    a `range(...)` is a list blob and calling it an `int` is wrong, but
    `print(range(3))` currently formats it as a number and is therefore already
    printing a blob address as if it were a count. Correcting the kind fixes
    `len` and has to be considered together with that, which is a change to the
    kind table rather than to the string representation.

    **`== STR_KIND` here and `string_operand_is_string` everywhere else is not an
    oversight, and it is the one decision this row has to get right.**
    `FOREIGN_BYTES_KIND` is a `char *` in every respect except the one that
    matters for a LENGTH: its bytes are the kernel's, so `strlen` answers in
    bytes where CPython answers in characters, and the whole reason the kind
    exists is that the build cannot tell which of the two it is holding. So it
    falls through to `None` — a refusal by name — while every other
    string-shaped question (`==`, `in`, `%s`, `print`, a method) is answered
    through `string_operand_is_string`, which admits it. Writing
    `string_operand_is_string` HERE would answer `len()` in bytes for a
    directory entry and reproduce, in one line, the defect the kind was added to
    remove.
    """
    if kind == STR_KIND:
        return LEN_FROM_STRLEN
    if is_list_kind(kind) or lowers_to_counted_blob(expr):
        return LEN_FROM_BLOB_FIELD
    return None


# The call-shaped things this path materialises as a `[count][elements]` blob
# and that the kind table does not (yet) classify as one. `range` is the only
# member; the container LITERALS are already `list_kind(...)` by
# `ValueKinds.kind_of`, and a comprehension too, so they need no row here.
# Named rather than inlined so that the reason above has one place to live.
_COUNTED_BLOB_CALLEES = ("range",)


def lowers_to_counted_blob(expr) -> bool:
    """True when `expr` is emitted as a blob whose first 8 bytes are its count.

    A LOWERING fact and not a kind fact, which is why it is a predicate over
    the node and not a row in the kind table: it is consulted only by
    `len_operand_lowering`, and only because the kind table does not yet say
    this. See that function for the `range` case and for why the kind is left
    alone rather than corrected here.
    """
    if isinstance(expr, F.CallExpr):
        return _flat_callee(expr) in _COUNTED_BLOB_CALLEES
    return False


def len_refusal(kind, spelled: str, slot_ann: str = None,
                 slot_kind: str = None) -> str | None:
    """Why `len({spelled})` cannot be lowered, or None when it can.

    One message for both backends, and it says which of the two things is
    missing rather than restating the rule:

      * a string's length is a `strlen` over its bytes, so a refusal here means
        the operand is NOT known to be a string, not that strings have no
        length;
      * a blob's length is its count field, so an int has no such field and
        reading offset 0 of it is a word, not a count;
      * a FRAME ADDRESS is the case that is most worth its own sentence,
        because the number it would produce is the most plausible-looking one
        in the whole family: offset 0 of a frame is the struct's FIRST FIELD,
        so `len(self.inner)` over a two-field struct returns that field's value
        — a number, of the right magnitude, meaning nothing. Before
        `FRAME_KIND` existed this case was filed under "the source does not
        say", which is FALSE about a declared field, and told the reader to
        annotate a field that is already annotated two lines above;
      * a DECLARED container field is `frame_slot_value_refusal`, and the
        annotation is why: the type is settled and the VALUE is not;
      * an unclassified operand is the case that used to produce a number. It
        gets its own sentence, because it is the one a reader has to act on:
        annotate the name, or bind it to something this path can see the type
        of.
      * a TYPE is the row that was missing while the type-value construct
        existed, and it is here because the `None` row is false about it: the
        source spells the operand as a type at the use site, so "annotate it"
        is advice about a name that already has one. A tag is a word and a
        container is a count field or a run of bytes; there is no third reading
        of it.
      * FOREIGN BYTES is the row that is not about a representation at all: the
        value is a perfectly good `char *` and the question is what the KERNEL
        wrote into it. `FOREIGN_BYTES_KIND`'s own comment carries the
        measurement; what belongs here is that it is a distinct row rather than
        the `None` one, because "the source does not say what this operand
        holds" is FALSE about it — the source says `str` and CPython agrees,
        and what is missing is a fact about the target rather than a fact about
        the program.

    `slot_ann` / `slot_kind` are the DECLARED annotation of the operand's field
    and the kind that annotation gives, UNGATED by whether the slot's value is
    established — they are what the `(B2)` row quotes, and the gate in
    `struct_field_kind` is what suppressed the kind from the lowering decision.
    Both are PARAMETERS rather than things derived here because answering them
    needs the struct table and the holder's candidate list, which live on the
    backend; `frame_slot_declared_annotation` turns the candidates into the one
    agreed annotation.
    """
    how = len_operand_lowering(kind)
    if how is not None:
        return None
    if slot_ann is not None:
        slot = frame_slot_value_refusal(spelled, slot_ann, slot_kind)
        if slot is not None:
            return slot
    if kind == FRAME_KIND:
        return (
            f"len({spelled}) is len() of a FRAME ADDRESS — the address of a "
            f"block of 8-byte slots that is one struct's fields in declaration "
            f"order. There is no count anywhere in it: a blob's count is a "
            f"header word the blob itself carries, and a frame has no header. "
            f"Reading 8 bytes at offset 0 of a frame does not invent a length, "
            f"it reads the FIRST FIELD's value and calls it a count — which is "
            f"why the type this slot has was established (a struct of this "
            f"module whose receiver is a frame) before this refusal was "
            f"chosen. Read the field you mean: `len(self.xs)` where the field "
            f"is a list, or return the count from the object that has one. "
            f"If that struct declares a `__len__` then `len(x)` is "
            f"`x.__len__()` — a method of the receiver's own struct, which "
            f"this backend calls, and the build pass rewrites that spelling for "
            f"a bare name holding a frame and for a nested frame it placed. "
            f"This operand is neither: it is a frame address from a shape the "
            f"holder analysis could not settle to a struct (an untyped or "
            f"reassigned slot), so there is no field list to write the call "
            f"against. Bind it to a name, which is the same program with a "
            f"lifetime this analysis can see")
    if kind is None:
        return (
            f"len({spelled}) — the source does not say what this operand holds, "
            f"and on this path the two things len() can answer are told apart "
            f"by what the operand IS: a string is a bare char * whose length is "
            f"a strlen over its bytes to the NUL, and a list or tuple is a "
            f"frame-allocated blob whose count is its first 8 bytes. Reading 8 "
            f"bytes at offset 0 of an unclassified word is a plausible-looking "
            f"wrong number — for a char * it is the first eight CHARACTERS of "
            f"the string — so it is refused. Annotate it (`x: String`) or bind "
            f"it to a list, tuple, range or string literal this path can see "
            f"the shape of")
    if kind == INT_KIND:
        return (
            f"len({spelled}) is len() of a value classified as {kind!r}, and "
            f"an integer has no length: there is no count to read at offset 0, "
            f"and the word there is the integer itself. A string's length is a "
            f"strlen over its bytes and a list's is its count field, and an int "
            f"is neither")
    if is_foreign_bytes_kind(kind):
        return (
            f"len({spelled}) is len() of bytes the KERNEL supplied — a name "
            f"from readdir(3), a value from the environment, a path from "
            f"getcwd(3) — and this path cannot answer it. A `strlen` counts "
            f"BYTES and CPython counts CHARACTERS, and the two agree for every "
            f"ASCII name and disagree for every other one: measured on both "
            f"architectures, `sum(len(x) for x in listdir(d))` over a directory "
            f"holding `plain` and `héllo` answered 11 where CPython answers 10, "
            f"green build, exit 0, nothing on stderr. Nothing in the SOURCE "
            f"says what the kernel said — the declaration above this value is "
            f"`-> List[String]`, which is the honest word for a Python-level "
            f"list of `str` — so there is no spelling the build could read to "
            f"learn whether the name it is holding is ASCII, and a byte count "
            f"presented as a character count is the most plausible wrong number "
            f"in this file: a small positive integer, identical on both "
            f"architectures and stable across runs. Refused rather than "
            f"emitted. What this path CAN do with the same value: everything "
            f"that is a property of the BYTES is already right — `==` against a "
            f"literal, `in`, `startswith`, `printf(\"%s\", …)` and `print`, "
            f"because CPython writes the same bytes back out under its "
            f"`surrogateescape` handler. And if you want the byte count on "
            f"purpose, ask for it as bytes: `os.str_len({spelled})` is the "
            f"`strlen` this path would otherwise have emitted, spelled so that "
            f"the reader knows it is bytes")
    if kind == TYPE_KIND:
        # Its own row rather than the `None` one above, and this is the whole of
        # what the TYPE_KIND kind is for. The source DOES say what the operand
        # holds — it says `{spelled}`, which is a type — so "annotate it
        # (`x: String`)" is advice about a name that already has a type, and a
        # tag is not a container: it is one word, a hash of a type's name, with
        # no count field and no bytes behind it. Reaching this row needs the
        # type-value construct; without it a bare type name was UNCLASSIFIED and
        # landed in the `None` branch, which is why this sentence exists rather
        # than a reworded one.
        return (
            f"len({spelled}) is len() of a TYPE, and on this path a type in a "
            f"value position is one 64-bit TAG (a hash of the type's name, so it "
            f"is the same number in every unit of the image, which is what lets "
            f"`t == Int32` be an ordinary integer comparison). A tag is a word: "
            f"there is no count at offset 0 and no bytes behind it, so neither of "
            f"the two things `len()` can answer — a string's `strlen` over its "
            f"bytes, a blob's count field — applies. To ask how many elements a "
            f"container has, `len()` the container; to ask which type a value "
            f"has, compare it with the type, which is what a tag is for")
    return (
        f"len({spelled}) is len() of a value classified as {kind!r}, and this "
        f"path has no length to read for it. A string's length is a strlen "
        f"over its bytes to the NUL and a list's is the count field at offset "
        f"0 of its blob; nothing else here carries one, and returning the word "
        f"itself would be a plausible-looking wrong number")
