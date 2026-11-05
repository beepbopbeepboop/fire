from . import *

# ── Everything else that reaches an INTEGER path holding a `char *` ───────
#
# `string_concat_refusal` above is one operator out of a table, and the reason
# it is one operator is historical rather than principled: it was the operator
# whose failure was MEASURED (`[]` on arm64, SIGSEGV on x86-64) and so the one
# anybody looked at. Every operator below has the same cause — a string is a
# bare `char *`, so any operator that reaches the integer ALU or the flag-
# setting compare is operating on an ADDRESS — and every one of them BUILDS,
# RUNS and returns a number the source never wrote. Measured on the tree this
# was written on, for `s = "abc"; t = "bc"`, on BOTH backends:
#
#     s & t     69911496 (arm64)   45978594 (x86-64)
#     s | t     68191180           2872318
#     s ^ t         4                  28          <- the two architectures
#     s - t        -4                  -4             DISAGREE on a
#     s * 2      8062864            5302246         fabricated number
#     s // 2   -2147433998        -2128240118
#     s >> 1   -2107760164        -2147386903
#     ~s          8881076            3236815
#     -s       -36488120          -79725522
#
# and the RELATIONAL half is worse than a wrong number, because it is a wrong
# BRANCH: `if s < t:` is decided by the interning order of two literals in the
# text section, so the answer is a property of the image's layout rather than
# of the program. On the tree above `s < t` and `s <= t` were TRUE and
# `s > t` and `s >= t` were FALSE, on both backends, purely because `"abc"` is
# emitted before `"bc"`. Reordering the two literals in the source reverses
# every one of them.
#
# So: the same answer as for `+`, for the same reason. None of these is lowered.
#
# The ONE exception, and it is D3's decision rather than this file's, is
# `ptr + int` and `ptr - int` with exactly one string operand. That is real C
# pointer arithmetic, it is the idiom a caller who reached a `char *` through
# this path may have meant, and refusing it would turn a working program into a
# diagnostic over a case the model cannot see. `str_plus_int_still_arithmetic` in
# test_formal_run.py is the guard. Every operator below has NO such reading:
# `%` and `&` on a pointer are not C at all, `|` and `^` are bit operations on
# an address, and `*` would have to scale a pointer to mean anything, which is
# a GNU extension rather than the C this path emits.
STRING_RELATIONAL_OPS = ("<", ">", "<=", ">=")
STRING_BITWISE_OPS = ("&", "|", "^")
STRING_SHIFT_OPS = ("<<", ">>")
STRING_PRODUCT_OPS = ("*", "/", "//", "%", "**")
# `+` and `-` are absent deliberately: `string_concat_refusal` owns them for the
# two-strings case, and the one-string case is the pointer arithmetic above.
STRING_ARITHMETIC_OPS = (STRING_BITWISE_OPS + STRING_SHIFT_OPS
                         + STRING_PRODUCT_OPS + STRING_RELATIONAL_OPS
                         + ("-",))

# Unary operators with no meaning on a `char *`. `~` is a bit operation on an
# address; unary `-` is negation of one. `not` is here too and for a different
# reason — see `string_unary_refusal`.
STRING_ARITHMETIC_UNARY_OPS = ("-", "~")


# The operator as a table key. A trailing `=` marks an AUGMENTED form and the
# tables below are keyed on the bare operator, so `+=` looks up `+`.
#
# The membership test is `AUG_OPS`, NOT "ends with `=`": the comparison
# operators `<=`, `>=` and `!=` end with `=` and are not augmented, and
# stripping their `=` turned `s <= t` into a refusal that named `'<'` — a
# diagnostic about a different operator than the line the reader is looking
# at, which is the one thing a refusal must not be. `==` is excluded for the
# same reason, and it is why `string_concat_refusal`'s own operator set has
# always been safe to spell out.
def _bare_operator(op: str, spelled_op: str | None = None) -> str:
    if op.endswith("=") and op[:-1] in AUG_OPS:
        return op[:-1]
    return op


def string_arithmetic_refusal(op: str, left_kind, right_kind,
                              spelled_op: str | None = None) -> str | None:
    """Why `a {op} b` cannot be lowered when a `char *` is an operand, or None.

    `spelled_op` is what the DIAGNOSTIC should say, which is not always `op`:
    the augmented-assignment emitters strip the `=` (`+=` arrives as `+`), and
    a message that told somebody their `+=` was a `+` would be a small lie
    about the line they are looking at. The table is keyed on the bare operator;
    only the wording uses the spelling.

    The refusal is deliberately not split by whether one or both operands are
    strings, with ONE exception: see `STRING_ARITHMETIC_OPS` for why `+`/`-`
    with a single string operand is left alone. For everything else the answer
    is the same either way — a pointer in an integer operator is meaningless —
    so a message that distinguished them would be longer and say less.
    """
    bare = _bare_operator(op, spelled_op)
    if bare not in STRING_ARITHMETIC_OPS:
        return None
    if bare == "-":
        # `-` is the one operator whose refusal is `+`'s, so it goes through
        # the same function and inherits the same measured numbers. The
        # two-strings case is address minus address — the same missing buffer as
        # address plus address. The one-string case is `ptr - int`, which is
        # real C pointer arithmetic and is deliberately left alone; see the
        # note above on why `+`/`-` are absent from the general table.
        return string_concat_refusal(spelled_op or bare, left_kind, right_kind)
    if not (string_operand_is_string(left_kind)
            or string_operand_is_string(right_kind)):
        return None
    return _string_operand_refusal(bare, spelled_op, left_kind, right_kind)


def _string_operand_refusal(op: str, spelled_op, left_kind,
                            right_kind) -> str:
    """The shared wording for "this operator reached the integer path with a
    `char *` in it". One function so the two backends print the same sentence
    and so adding an operator does not mean writing a second paragraph."""
    shown = spelled_op or op
    which = "the left operand" if string_operand_is_string(left_kind) else (
        "the right operand" if string_operand_is_string(right_kind)
        else "an operand")
    return (
        f"{shown!r} is refused when {which} is a string. A string on this path "
        f"is a bare `char *`, so `{shown}` is an integer operation on an "
        f"ADDRESS, and it builds, runs and returns a number the source never "
        f"wrote: for `s = \"abc\"` and `t = \"bc\"`, `s ^ t` returned 4 on arm64 "
        f"and 28 on x86-64, `s * 2` returned 8062864 and 5302246, and "
        f"`s // 2` returned -2147433998 and -2128240118 — two architectures "
        f"disagreeing about a number neither of them computed. "        + ("Python orders strings lexicographically and this compares their "
           "addresses, so the branch is taken by the order the literals happen "
           "to be interned in the text section: `s < t` measured TRUE and "
           "`s > t` FALSE on both backends for no reason a reader of the "
           "program could see. Lexicographic order needs a three-way compare "
           "and this path has no symbol that provides one. "
           if op in STRING_RELATIONAL_OPS else "")
        + "The string operations that ARE lowered are `len`, `==`/`!=`, `is`/"
        "`is not`, `in`/`not in`, and the methods in POINTER_BOUNDED_METHODS; see "
        "STRING_LENGTH_SYMBOL for why a string's length and content equality "
        "are computations over its bytes rather than fields, and "
        "string_concat_refusal for the `+` half of this table")


def string_compare_number_refusal(op: str, left_kind, right_kind,
                                  left, right, spelled_op=None) -> str | None:
    """Why `a {op} b` cannot be a string comparison when ONE side is a number.

    THE OTHER HALF of `string_comparison_lowering`'s precondition, and it was
    live the moment `p[i]` on a declared pointer became a byte read. That
    lowering is `strcmp(a, b) == 0`, whose precondition is that BOTH operands
    are addresses, and it decided that by asking whether AT LEAST ONE side is a
    string — which is the right question for `a == "x"` and the wrong one for
    `p[0] == "."`.

    `p[0]` is a byte, a byte is an integer on this path, and `strcmp` was handed
    the byte's VALUE as an address. Measured, on this tree, arm64:

        def is_dot(name: Pointer[UInt8]):
            if name[0] != ".":
                return 0
            ...

    SIGSEGV, with no output at all — the number 46 is not a mapping. Before the
    pointer subscript landed the same line took the blob path, so this is a new
    way for the same spelling to be a crash, and a crash is the outcome the
    byte read was supposed to replace.

    It is refused rather than worked around, and the message gives both
    readings because both are right answers to different questions: the byte's
    value (`p[0] == 46`, with the byte code written as a number, which is the
    same rule `os/path`'s `SLASH` and `DOT` constants are there for), or the
    string's content (`str_at(s, 0, ".")`, or `s.startswith(".")`).

    NOT the same arm as the null test, and both are asked from the same pair of
    operands: `p == 0` is "is it there", which IS a word compare and is what
    every function in `os` means by it; `p[0] == "."` is a number against a
    string, which is nothing.
    """
    if (spelled_op or op) not in ("==", "!="):
        return None
    if left is None or right is None:
        return None
    if string_is_null_test(left, right):
        return None
    if not (string_operand_is_string(left_kind)
            or string_operand_is_string(right_kind)):
        return None
    # EXACTLY ONE side classified. `None` counts as "not a string" on purpose:
    # `p[0]` on a `Pointer[UInt8]` is definitively a byte and `ValueKinds`
    # reports None for it, because a subscript's element kind is not something
    # the whole-function scan derives. Requiring INT_KIND would have missed the
    # measured case exactly, and it would have missed a `char *` from an
    # unannotated callee too — which is a crash by the same route.
    if (string_operand_is_string(left_kind)
            == string_operand_is_string(right_kind)):
        return None
    # The STRING side is `txt` and the other is `num`, whichever side it is on.
    num, txt = ((right, left) if string_operand_is_string(left_kind)
                else (left, right))
    return (
        f"`{spelled(left)} {spelled_op or op} {spelled(right)}` compares a "
        f"NUMBER with a string, and the string comparison this would lower to "
        f"is `strcmp`, which DEREFERENCES both operands — so it would be handed "
        f"the value of `{spelled(num)}` as an address. Measured on this tree: "
        f"`p[0] != \".\"` on a `Pointer[UInt8]` segfaults with no output, "
        f"because a byte is a number here and the number is not a mapping. "
        f"Python has no such comparison at all: it is False for every pair. "
        f"Ask one of the two questions instead — the byte's value, "
        f"`{spelled(num)} == 46` with the byte written as a number (the same "
        f"rule `os.path`'s `SLASH` and `DOT` constants exist for, since a "
        f"character argument to a C library call is an `int` there), or the "
        f"string's content, `str_at({spelled(txt)}, 0, \".\")` or "
        f"`{spelled(txt)}.startswith(\".\")`")


#: The two container budgets, as NAMED CONSTANTS, and the answer to "which
#: machine decides".
#:
#: They are two numbers about two frames, and they used to be two literals in
#: two emitters (`formal/arm64_codegen.py::_SCRATCH`, `formal/x86_64_codegen.py::
#: _BLOB_BYTES`) with the values spelled again in this function's docstring and
#: again in the fuzzer's comment. A refusal message that states a budget, a
#: corpus row that sizes a program to a budget, and a frame layout that is set
#: by a budget are three facts about one number, and three copies of it is three
#: chances to be wrong about which machine refuses what.
#:
#: They differ on purpose. arm64's `SUB SP, SP, #_SCRATCH` is one 12-bit-immediate
#: scaled instruction (`_SCRATCH = 32 << 12`), and x86-64's blob region has to
#: survive the frame arithmetic its own locals and spill area are laid out
#: against, so raising it is a frame-layout change with a proof obligation on
#: `lib/X86.lean`'s stack-floor and frame-bound lemmas — not a constant to edit.
#: What IS a constant to edit is the ANSWER, and this is it: **the smaller
#: budget decides anything that must hold on both machines.**
#:
#: Concretely: a program this backend calls buildable fits `CONTAINER_BUDGET`,
#: so a corpus, a fixture or a doc that says "this program builds" is sized from
#: the smaller of the two, and a `REFUSAL-DIVERGES` whose refusal is this one is
#: a fact about the FRAME rather than a capability difference between the
#: backends (`tools/formal_fuzz.py::_is_frame_budget_refusal` is what tells the
#: two apart in a tally).
ARM64_CONTAINER_BUDGET = 131072          # 128 KiB, the frame scratch
X86_64_CONTAINER_BUDGET = 16384          # 16 KiB, the blob region

#: The budget that decides, for anything that has to hold on BOTH machines.
CONTAINER_BUDGET = min(ARM64_CONTAINER_BUDGET, X86_64_CONTAINER_BUDGET)


def blob_ceiling(budget: int) -> int:
    """How many 8-byte elements fit in `budget` bytes of frame blob region.

    A word-element blob is `[count][element...]`, so eight bytes of the budget
    are the count and the rest are elements. This is the arithmetic
    `frame_blob_refusal` prints ("at most N element(s) fit in what is left
    here") and it is here, once, because the corpus sizes a program against the
    same edge — `tools/formal_fuzz.py`'s `big_blob` row — and two copies of the
    arithmetic is two answers to "where is the ceiling".
    """
    return max(0, (budget - 8) // 8) if budget > 8 else 0


def frame_budget_phrase() -> str:
    """The one sentence that names both budgets, for a message or a comment.

    It exists because `frame_blob_refusal` needs the pair and so does anything
    that has to explain a size to a reader who is deciding which machine they
    are on, and writing the two numbers twice is how they stop agreeing.
    """
    return (f"arm64's frame scratch is {ARM64_CONTAINER_BUDGET} bytes and "
            f"x86-64's blob region is {X86_64_CONTAINER_BUDGET}, so "
            f"{CONTAINER_BUDGET} is the budget a program has to fit to build on "
            f"both")


def frame_blob_refusal(what: str, wanted: int, available: int) -> str:
    """The ONE message for "this container does not fit in the frame", for both
    backends and every container shape.

    Containers on this path are frame-allocated: a list, tuple, dict or string
    blob is a run of 8-byte slots below the frame pointer, out of a budget the
    function's whole body shares, and a literal reserves its whole blob before
    any element is evaluated (so a nested container lands above its parent
    rather than inside the region the parent is still filling). The limit is
    therefore real and architectural, and the two backends have DIFFERENT
    budgets — `ARM64_CONTAINER_BUDGET` and `X86_64_CONTAINER_BUDGET`, both
    declared above, and the reason the number has to be computed and printed by
    one place instead of formatted at each call site.

    What each backend used to print was the two sides of its own comparison, and
    on x86-64 those are negative FRAME OFFSETS, not sizes: a 4095-element list
    literal read "list literals exceed the formal frame (16368 > -16 bytes)",
    which is a true statement about two numbers and no help at all to a reader.
    So the callers pass SIZES, and this prints sizes, plus the one number a
    caller can act on: how many elements would fit, derived from the budget the
    same way the emitters derive the blob size (a word-element blob is
    `[count][element...]`, so eight bytes of the budget are the count).

    The remedy sentence names the two things that actually work, because the
    obvious one does not: the frame is not something a caller can enlarge from
    the source, and a per-element store loop would still need the blob to exist.
    Splitting the literal across two functions gives each its own budget;
    building the container at run time (appending to a list literal sized for
    what the program needs) does not put the whole thing in the frame at once.
    """
    words = blob_ceiling(available)
    return (f"{what} does not fit in the frame: it needs {wanted} bytes and "
            f"this function has {available} left for containers. A blob of "
            f"8-byte elements is [count][element...], so at most {words} "
            f"element(s) fit in what is left here — and the budget is shared "
            f"with every other list, dict, string and receiver frame in the same "
            f"body. Build the container at run time (append into a list literal "
            f"sized for what the program needs), or split it across two "
            f"functions so each gets its own budget.")


#: The element-count estimate for a blob whose length this path cannot read.
#: It was a bare `64` written into each backend's `_blob_est` as the fallback
#: arm, which made it a frame-budget decision with two copies; it is here
#: because the loop-growth arithmetic below multiplies it and a reader has to
#: be able to find the number that gets multiplied.
BLOB_ESTIMATE_FALLBACK = 64


def loop_trip_count(start, stop, step):
    """`len(range(start, stop, step))`, or None when a bound is not a literal.

    The one place the "how many times can this loop run" question is asked, so
    that a `for … in range(2, 40, 3)` and a `for … in range(70)` cannot get two
    different answers from two hand-written formulas. `None` means "no
    compile-time bound", which is a distinct answer from `0` — an empty range
    really does run zero times, and a loop whose bound is a runtime value does
    not.
    """
    if start is None or stop is None or step is None:
        return None
    try:
        return len(range(int(start), int(stop), int(step)))
    except (TypeError, ValueError):
        return None


def blob_loop_growth(entry: int, once: int, trips: int) -> int:
    """Elements a blob-producing SITE must reserve when it sits inside a loop.

    A blob on this path is a fixed-size block of the frame, and the reservation
    is made ONCE per site — the emitted code is one copy, however many times it
    runs. That is sound only while the site executes at most once, and the
    commonest way to build a list breaks it: `s = s + [x]` and `s.append(x)`
    inside a loop both produce a value the NEXT iteration reads, so the last
    iteration's blob is longer than the first's by a factor of the trip count.

    Measured on both architectures, the same three-line program:

        var s = [0]
        for i in range(K): s = s + [1]
        printf("len=%d", len(s))

    x86-64 built, linked and exited 1 having printed nothing at `K = 65` and
    answered correctly at `K = 64`, because the site's estimate was
    `blob_est(s) + 1 = 64 + 1 = 65` words — the fallback above, plus the one
    element appended. arm64 has no guard on that path at all and overran its
    own reservation by `K - 65` words, which is a frame corruption rather than
    a wrong number: a callee's copy of the same loop returned the right length
    and its caller's `printf` printed nothing. The identical shape with
    `s.append(1)` instead stopped at `K = 2` on BOTH machines, because an
    append's capacity is the number of append SITES in the function.

    `entry` is the longer operand as it stands on entry to the loop, `once` is
    the single-execution bound `_blob_est` already computes, and `trips` is
    `loop_trip_count`'s answer. The growth is per ITERATION, so the total is
    `entry + (once - entry) * trips` rather than `once * trips` — which is what
    keeps `for x in ys: s = s + [x]` (with `ys` a blob of unknown length, so
    `once` is dominated by the fallback) reserving what it reserved before
    instead of 64 times as much.
    """
    per = max(1, int(once) - int(entry))
    return max(0, int(entry)) + per * max(1, int(trips))


def stmt_bound_names(stmts) -> set:
    """Every name a statement list BINDS, at any depth inside it.

    The question a loop's reservation asks is "does this loop's body rebind a
    name this site reads?", and the answer has to include the rebinding that
    happens inside a nested `if`, a nested loop or a `try`, because the loop
    still executes them. A nested `def`/`lambda` is deliberately NOT descended
    into: its body runs on its own schedule, and a name it binds is not one
    this loop's iterations can see.

    `iter_nodes` is not used because it descends into everything, nested
    functions included, and because the answer wanted here is TARGETS rather
    than every name mentioned — a body that only READS `s` does not make the
    site that reads `s` loop-carried.
    """
    out: set = set()
    for stmt in stmts or ():
        _collect_bound_names(stmt, out)
    return out


def _collect_bound_names(stmt, out: set) -> None:
    if isinstance(stmt, (list, tuple)):
        for s in stmt:
            _collect_bound_names(s, out)
        return
    if stmt is None or not hasattr(stmt, "__dataclass_fields__"):
        return
    if isinstance(stmt, (F.FunctionDef, F.LambdaExpr)):
        return
    # A loop's own TARGET is not in this set: the counter is bound by the loop
    # rather than by its body, and a site that reads it is reading the counter,
    # not a value the body grows.
    if isinstance(stmt, (F.AssignStmt, F.AugAssignStmt, F.VarDecl,
                         F.MultiAssignStmt)):
        for name in assignment_target_names(stmt):
            out.add(name)
    for field in ("body", "then_body", "elifs", "else_body", "orelse",
                  "finalbody", "handlers"):
        value = getattr(stmt, field, None)
        if value:
            _collect_bound_names(value, out)


def blob_names_read(expr) -> set:
    """The plain names an expression MENTIONS.

    Over-approximating on purpose and saying so: a name that appears as a
    subscript base, a call's callee or an attribute's object is counted, which
    can only make a site look loop-carried when it is not. The cost of that
    over-approximation is a reservation multiplied by a trip count it did not
    need — frame bytes, and in the worst case a `frame_blob_refusal` — while
    the cost of missing a rebinding is a program that writes past its own
    reservation, so the direction is fixed.
    """
    return {n.name for n in iter_nodes(expr)
            if isinstance(n, F.IdentExpr) and isinstance(n.name, str)}


def walk_stmt_trips(stmts, loop_trips):
    """`(node, trips)` for every AST node in `stmts`, with its execution bound.

    `trips` is an upper bound on how many times the node's enclosing code runs:
    1 outside any loop, the loop's own bound inside one, and the PRODUCT in a
    nested one. `None` means "no compile-time bound" and it propagates — a node
    inside a `while` inside a `range(70)` has no bound, and rounding that down
    to 70 is how a capacity ends up a promise the program cannot keep.

    `loop_trips(stmt)` is the caller's reader for a loop statement's header,
    because only the caller knows how to evaluate the expressions in it
    (`_range_info` plus `_static_int` on one side, `_blob_iter_trip_bound` on a
    container iterable). It is asked only about the statement kinds that are
    loops, and any other statement is one execution. A nested `def`/`lambda`
    body is not descended into: it runs on its own schedule.

    One pass over the node fields, rather than `iter_nodes` per statement: the
    second is quadratic in the size of a function, and this runs once per
    function over the whole stdlib.

    The whole-function scan exists because an append's capacity is a property
    of the FUNCTION, not of the site: the blob is reserved where the literal
    is, which is usually nowhere near the `append` that grows it, so the two
    ends have to be counted together — the same reason `_scan_list_caps`
    returns two maps. This is the loop-aware half of that count.
    """
    out = []

    def walk(node, trips):
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child, trips)
            return
        if node is None or not hasattr(node, "__dataclass_fields__"):
            return
        if isinstance(node, (F.FunctionDef, F.LambdaExpr)):
            return
        bound = trips
        if isinstance(node, (F.WhileStmt, F.ForStmt, F.ComptimeForStmt)):
            here = loop_trips(node)
            bound = None if (trips is None or here is None) else trips * here
        out.append((node, bound))
        for field in _node_field_names(node):
            walk(getattr(node, field), bound)

    walk(stmts, 1)
    return out


# The number of slots a list literal containing `*xs` reserves for a DYNAMIC
# operand. One number, in one place, because it is a frame-budget decision
# that both backends make and a disagreement between them is a program that
# builds on one machine and dies of the capacity guard on the other.
DYNAMIC_SPLAT_SLOTS = 8


def dynamic_splat_capacity(elements, literal_operand) -> int:
    """Slots to reserve for a list literal whose `*` operands are spliced.

    A literal operand contributes its own length, because it is known here; a
    dynamic one has no compile-time length, so it contributes
    `DYNAMIC_SPLAT_SLOTS`.

    **That cap is a budget choice, not the semantics, and it is the reason a
    long splat exits 1 rather than answering.** The append path's guard
    (`list_append_overflow_message`'s subject) fires when the run-time count
    reaches the reservation, and a source longer than `DYNAMIC_SPLAT_SLOTS`
    reaches it: `a = [1..10]; b = [*a]` appends ten elements into eight slots
    and stops. That is measured, on both backends, and it is the SAFE direction
    — a named limit rather than a wrong answer — but it is a real ceiling and
    it is shared with every comprehension, whose cap is likewise a number of
    append sites rather than a length.

    Both facts are here so that neither backend re-derives the number: it was
    arm64's `static_n += 8` written inline in its emitter, and an x86-64 copy
    that had to agree with it by reading the comment.
    """
    n = 0
    for el in elements or []:
        if _is_star_unpack(el):
            if literal_operand(el.operand):
                n += len(el.operand.elements)
            else:
                n += DYNAMIC_SPLAT_SLOTS
        else:
            n += 1
    return max(1, n)


def _is_star_unpack(el) -> bool:
    """Whether `el` is a list element spelled `*operand`.

    `F.UnaryOp` with `op == "*"` and nothing else: `*a` in a list literal is
    the only place this spelling appears, and a `-a` or `not a` reaching the
    same test must not be read as an unpack.
    """
    return (isinstance(el, F.UnaryOp) and el.op == "*"
            and hasattr(el, "operand"))


def literal_splat_operand_is_static(op) -> bool:
    """Whether a `*` operand's length is known at compile time.

    The one predicate both backends ask before deciding between "expand it
    here" and "loop over it at run time", so the two cannot disagree about
    which of the two a given `[*…]` is.
    """
    return isinstance(op, (F.ListExpr, F.TupleExpr, F.SetExpr))


def dict_literal_static_pairs(literal) -> int:
    """The pairs a dict literal's own construction writes into its blob.

    `len(pairs)` minus the ones a `**`/`*` splat contributes nothing to: a
    splat pair is evaluated for its side effects and then skipped, so the blob's
    `count` word is this number and not the number of pairs written.

    **This is the rule `_emit_dict` used to state for itself, and it now reads
    it from here**, because the reservation the insert path needs is `this +
    the number of store sites` and a count computed two ways is two numbers
    that agree until the day one of them is edited — which is a write past the
    blob rather than a failure.
    """
    n = 0
    for k, v in (getattr(literal, "pairs", None) or ()):
        if isinstance(k, F.UnaryOp) and k.op in ("**", "*"):
            continue
        if v is None:            # `**` with the operand in the key slot
            continue
        n += 1
    return n


def dict_store_sites(fn) -> dict:
    """`{name: sites}` — this function's `d[k] = v` count, per dict NAME.

    A plain ASSIGNMENT only, and that is a language fact rather than a
    narrowing: CPython's `d[k] = v` INSERTS when the key is absent, while
    `d[k] += v` first READS and so raises `KeyError` on a missing key. The
    augmented form therefore belongs to the read path — which is where it
    already is, and where exiting on a miss is the right answer.

    A bare NAME base only, for the same reason `list.append`'s capacity is
    counted per receiver name: `_emit_dict` has the literal NODE and the store
    has the NAME, so a table keyed by both is the only shape both ends can read
    (`list_literal_reserved_slots`'s own note says the same about appends).
    """
    out: dict = {}
    for node in iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(node, F.AssignStmt):
            continue
        target = getattr(node, "target", None)
        if not isinstance(target, F.SubscriptExpr):
            continue
        if not isinstance(target.obj, F.IdentExpr):
            continue
        out[target.obj.name] = out.get(target.obj.name, 0) + 1
    return out


def _literals_bound_to(fn, name: str) -> list:
    """Every container literal `fn` binds `name` to, whatever its kind."""
    out = []
    for node in iter_nodes(getattr(fn, "body", None) or []):
        value = _binding_value(node, name)
        if isinstance(value, (F.ListExpr, F.DictExpr, F.SetExpr, F.TupleExpr)):
            out.append(value)
    return out


def _binding_value(node, name: str):
    """The value a binding statement gives `name`, or None if it binds another.

    The two shapes a binding comes in, and they are two shapes because the
    PARSER made them two: `b = bytearray()` is an `AssignStmt` with an
    `IdentExpr` target, and `var b = bytearray()` is a `VarDecl` with a plain
    `name`. Two readers of that used to exist — `_literals_bound_to` here and
    each backend's `_list_literals_bound_to` — and they agreed only because
    both spelled both arms out. One helper, both callers, and the append-capacity
    scan and the literal census cannot drift about which statements bind a name.
    """
    if isinstance(node, F.AssignStmt):
        return node.value if _target_binds_name(node.target, name) else None
    if isinstance(node, F.VarDecl) and node.name == name:
        return node.value
    return None


def _target_binds_name(target, name: str) -> bool:
    """Whether an assignment target introduces the local `name`.

    Direct, or one level of tuple/destructuring. An assignment target is always
    a NODE (`fire_compiler` gives a `ForStmt` a bare STRING target instead, and
    neither caller here has a for-target to read), so there is no string
    spelling to handle — which is also why this is not the emitters'
    `_binds_name` moved wholesale: that one answers the string case for a
    for-target walk, and splitting a target STRING by hand here would be a
    second implementation of `mojo.middle/boundnames`'s own reader.
    """
    if isinstance(target, F.IdentExpr):
        return target.name == name
    if isinstance(target, (F.TupleExpr, F.ListExpr)):
        return any(_target_binds_name(el, name) for el in target.elements)
    return False


def dict_store_capacity(fn, sites) -> tuple:
    """`({id(literal): pairs}, {name: pairs})` — the room a dict literal must
    reserve for the `d[k] = v` that follow it.

    The `list.append` arrangement exactly (`_scan_list_caps` in both backends),
    and for the same reason: a dict pair-blob is `[count][k0][v0]…` carved out
    of the frame at a COMPILE-TIME size, so an insert has nowhere to write
    unless the literal reserved the room, and the number of store SITES in the
    function that built it is a sound bound for straight-line code. Every
    EXECUTION of a site counts against it, and the store is checked against it
    at run time — so a store in a loop stops the program loudly instead of
    writing past the blob.

    Two tables because the two ends are different places and both must be
    computed from one pass: `_emit_dict` has the literal, the store has the
    name. A name bound to more than one literal takes the smallest capacity, so
    the bound holds whichever blob is live.

    **A name this function also binds to a NON-dict container gets no entry.**
    Its capacity would be a promise about the wrong blob, and a promise about
    the wrong blob is a write past the end of the right one. The same guard as
    `_scan_list_caps`'s `is_list_kind` test, for the same reason — the store
    then says it cannot insert rather than inserting into a list.
    """
    by_node: dict = {}
    by_name: dict = {}
    for name, count in (sites or {}).items():
        bound = _literals_bound_to(fn, name)
        literals = [lit for lit in bound if isinstance(lit, F.DictExpr)]
        if not literals or len(literals) != len(bound):
            continue
        want = min(dict_literal_static_pairs(lit) for lit in literals) + count
        for literal in literals:
            prev = by_node.get(id(literal))
            by_node[id(literal)] = want if prev is None else min(prev, want)
        by_name[name] = want
    return by_node, by_name


def diagnostic_length(text: str) -> int:
    """The length a `write(2, text, …)` of this text must be given, in BYTES.

    **The run-time stops write their message with a LENGTH, and a length is a
    byte count while every message in this module is a Python `str`.** The two
    agree only while the text is ASCII, and five of the seven messages a formal
    image can write to fd 2 are not: measured on this tree, both architectures,
    `list_append_overflow_message("ys", 1)` is 774 characters and 778 bytes (two
    `—`/`…`), and `write` was handed 774 — so the last four bytes never left
    the program and the message ended mid-word:

        formal: list.append overflowed 'xs': … so the overflow follows the appe

    which is the same defect class as the silence this message replaced, one
    step down: the reader is told the bound and then loses the last sentence,
    which is the one naming what does NOT help. The same measurement for
    `dict_store_overflow_message`, `dict_store_no_room_message`,
    `dict_store_other_blob_message` and `blob_growth_overflow_message` loses 2-4
    bytes each; `int_parse_trap_message` and `int_overflow_trap_message` are
    ASCII today and lose nothing, which is exactly why this went unnoticed —
    two emitters with `len(text)` are correct for every message that has no
    typographic punctuation in it.

    So the emitters ask THIS, in both of them, rather than each writing `len()`:
    one reader for "how many bytes is this text", because the length and the
    bytes come from two different places (the buffer is interned by
    `_intern_string`, the count was computed at the call site) and two
    independent answers to one question is how the fourth word of a message
    diverges between architectures. The typographic characters are NOT the
    defect and are not removed: every other diagnostic on this path is written
    with them, and `test_formal_run.py`'s `STDERR_EXACT_CASES` compares each
    stop's stderr against the message this module builds, byte for byte, so a
    re-truncation is a red row rather than a sentence nobody reads to the end.
    """
    return len(text.encode())


def dict_store_overflow_message(name: str, capacity: int) -> str:
    """The ONE text a `d[k] = v` that has run out of room writes to fd 2.

    `list_append_overflow_message`'s sibling and its exact twin in purpose: a
    run-time message rather than a compile-time refusal, because the capacity
    is the number of store SITES and every EXECUTION of a site counts against
    it, so `while i < 3: d["k"] = i` is one site run three times and no pass
    over the source can say it fits.

    Shared by both backends for the reason that one is: two architectures
    printing two different sentences for one limit is how a reader ends up
    looking for a construct one of them invented.
    """
    return (f"formal: a dict store into {name!r} overflowed its pair blob: its "
            f"capacity is {capacity} pairs — the number the literal wrote plus "
            f"one for each `d[k] = v` SITE in the function that built it — and "
            f"every EXECUTION of a site counts against it, so a dict built in a "
            f"loop outgrows the room the frame reserved for it. There is no heap "
            f"on this path, so the blob cannot grow. Build the dict with the "
            f"keys it needs at construction time, or move the stores into a "
            f"function of their own so the capacity each one sees is its own.")


def dict_store_no_room_message(name: str, key: str) -> str:
    """Why a `d[k] = v` on a blob this build cannot size stopped.

    The two cases a reservation cannot reach, and they are DIFFERENT problems
    with different repairs, so they say different sentences:

      * the base is not a local bound to a dict LITERAL in the function being
        emitted — a struct field, a call's result, a `Dict[…]` parameter. The
        blob was built somewhere else, so this build never saw its pairs and
        cannot reserve for an insert. The repair is to give the table the key
        at the place that builds it.
      * the key is a statically-known CONTAINER, which this path compares
        element-wise against canonical values and never materialises, so there
        is no key WORD to write on an insert. The repair is a key this path
        can hold in one word.

    Before this the second case and the first were one silent `exit(1)`, which
    is the worst of the three answers this path can give: not a wrong number a
    reader can compare, not a named refusal they can act on, but silence.
    """
    return (f"formal: a dict store of {key!r} into {name!r} needs a pair this "
            f"build cannot reserve. The key is a statically-known container, "
            f"and this path compares such a key element-wise against "
            f"canonical values without ever materialising it, so an insert has "
            f"no single word to write — nothing about the table's size is "
            f"wrong; the key spelling is. Use a key this path holds in one "
            f"word (a string or an integer).")


def dict_store_other_blob_message(name: str, key: str) -> str:
    return (f"formal: a dict store of {key!r} into {name!r} needs a pair this "
            f"build cannot reserve, because the blob was not built by a dict "
            f"LITERAL in this function: its pairs were written somewhere else, "
            f"so there is no reservation here to add to and the count this "
            f"store would bump has no room behind it. Give the table the key "
            f"where it is built — a dict literal with the entry already in it "
            f"— or copy it into one built here first.")


def list_literal_reserved_slots(literal) -> int:
    """How many element slots a list literal's own construction occupies.

    `len(literal.elements)` for an ordinary literal, and
    `dynamic_splat_capacity` for one with a `*` operand — because a splat
    literal builds its blob by APPENDING, so what it occupies is the cap it
    reserved, not the number of `*` operands written in it.

    **This is what the append path's bound is made of, and getting it wrong
    makes a legal program overflow.** `xs = [1, 2]; xs.append(3)` reserves
    `len(elements) + append_sites` and is fine. `xs = [*a]; xs.append(3)` did
    not: the bound counted the `*a` as ONE element, so a two-element `a` plus
    one append hit a capacity of 2 and the guard stopped the program with
    `list.append overflowed 'xs': its capacity is 2` — on both backends,
    because both computed the bound the same wrong way. The blob itself holds
    `dynamic_splat_capacity` slots, so the bound has to be stated in the same
    units the reservation is.
    """
    if any(_is_star_unpack(el) for el in (literal.elements or [])):
        return dynamic_splat_capacity(literal.elements,
                                      literal_splat_operand_is_static)
    return len(literal.elements or [])


#: Node kinds whose blob is a `[count][element…]` this expression BUILDS at its
#: own site, as opposed to a name it reads or a subscript that borrows one. A
#: comprehension's ELEMENT, evaluated inside the generator loop, is therefore
#: re-materialised into the SAME frame words on every iteration — which is what
#: `comprehension_element_owns_container` is asked about.
_OWNS_ITS_BLOB = (F.ListExpr, F.TupleExpr, F.SetExpr, F.DictExpr,
                  F.Comprehension, F.SliceExpr)


def _materialises_a_container(node) -> bool:
    """True when `node` builds a container blob at the site it is written at.

    Deliberately excludes a bare NAME, and the exclusion is the language rather
    than a narrowing: `[one for y in ys]` binds the same list object to every
    element in CPython too, so aliasing it is the RIGHT answer. It also excludes
    `or`/`and`, which return the deciding operand rather than a new container
    (`_emit_and_or` in each backend), while `+`, `|` and `*` build one and are
    included.
    """
    if isinstance(node, _OWNS_ITS_BLOB):
        return True
    if isinstance(node, F.BinaryOp) and node.op in ("+", "|", "*"):
        return (_materialises_a_container(node.left)
                or _materialises_a_container(node.right))
    return False


def comprehension_element_owns_container(node) -> bool:
    """True when a comprehension's ELEMENT builds a container of its own.

    **Asked of the ELEMENT expression, not of the comprehension** — see
    `comprehension_element_borrowes_inner_container`, whose subject is the same
    expression, and the two are different questions about it.

    The shape `[[y] for y in ys]` has and `[x + y for x in ys]` does not, and the
    difference is the whole of a defect this path used to answer with a wrong
    number rather than with a refusal: the element's blob is reserved ONCE, at
    the element's own site, so every iteration of the generator OVERWRITES it and
    the append copies the ADDRESS — which means every element of the result is
    the same container and holds the LAST iteration's contents. Measured on both
    architectures, `s = 0; for v in [[x + y for x in [1, 2]] for y in [10, 20,
    30]]: s = s + v[0]` answers 93 where CPython answers 63 (93 = 31 x 3).

    **A bare name is excluded and must stay excluded.** `[one for y in ys]` is
    three references to ONE list in CPython, so a per-iteration copy of it would
    be the bug in the other direction. A CALL that returns a container is
    included, and it needs no separate rule: the caller reserves the callee's
    block at the call's own site (`container_returned_blob_sites`), so
    `[mk(y) for y in ys]` rewrites one block per iteration exactly as a display
    does.
    """
    return _materialises_a_container(node)


def comprehension_element_borrowes_inner_container(node) -> bool:
    """True when the blob `node` BUILDS holds the address of a container `node`
    ALSO builds, so the two are one object across evaluations.

    Asked of a comprehension's ELEMENT expression — the blob that gets the
    per-iteration copy — and **one level, not a descent**, because the question
    is only ever about that blob's own words. Copying them gives each iteration
    its own copy of this container, and every word in that copy is right, except
    a word that is the ADDRESS of a container the same expression rebuilt: the
    copy is right and the thing it points at is still the one site every
    iteration shares.

    `[[[i] for i in [y]] for y in [10, 20, 30]]` is the smallest program that
    shows it. The element is a comprehension, its result blob holds one word —
    the address of the `[i]` blob the same element expression rebuilds each time
    it runs — and the sum of `v[0][0]` comes back 90 where CPython answers 60.

    Each `False` below is its own reason rather than a gap: a concat, a
    repetition and a slice put their operands' WORDS in the result (a slice's
    source is not rebuilt per iteration), and a generator's ITERABLE is not an
    element position at all — which is why `[[x + y for x in [1, 2]] for y in ys]`,
    whose inner comprehension iterates a list display, is `False` and is
    answered by the copy.
    """
    if isinstance(node, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        return any(_materialises_a_container(el) for el in (node.elements or []))
    if isinstance(node, F.DictExpr):
        return any(_materialises_a_container(k) or _materialises_a_container(v)
                   for k, v in (node.pairs or []))
    if isinstance(node, F.Comprehension):
        return (_materialises_a_container(node.element)
                or _materialises_a_container(node.key))
    return False


def comprehension_element_shared_inner_message(node) -> str:
    """Why a comprehension whose element holds a container of its own is refused.

    One sentence for both backends because the shape is one shape: it is decided
    here, from the source, and neither emitter gets to answer it differently.
    """
    return (
        f"formal: this comprehension's element builds a container INSIDE "
        f"another container, so the outer one holds the address of the inner one "
        f"rather than its words, and both are rebuilt in place on every "
        f"iteration. A per-iteration copy of the outer blob gives every element "
        f"its own outer container and leaves the inner one shared, which is the "
        f"same aliasing one level down: `[[[i] for i in [y]] for y in [10, 20, "
        f"30]]` answers 90 where CPython answers 60. Copying it properly means "
        f"relocating the inner addresses as well, and this path has no way to "
        f"know which words of a blob are addresses. Refused rather than answered "
        f"with a number that is wrong; a comprehension whose element is a single "
        f"container — `[[y] for y in ys]` — is answered, because a word copy of "
        f"that one is the whole of it."
    )


def blob_reserved_slots(node) -> int:
    """How many element slots a blob-constructing NODE's own construction takes.

    Two shapes, one question, because `xs = []; xs.append(3)` and
    `xs = bytearray(); xs.append(3)` are the same program and the append bound
    is made of the number this returns:

      * a container LITERAL — `list_literal_reserved_slots`, which is
        `len(elements)` or the splat capacity;
      * a blob CONSTRUCTOR call — `blob_constructor_lowering`'s `elem_count`,
        which is 0 for `bytearray()` and `List()` and `bytearray(3)`'s 3 for
        `bytearray(3)`.

    A node that is neither has no answer here, and `blob_nodes_bound_to` is
    what guarantees a caller never hands one over: it returns only nodes that
    construct a blob. That is why the dispatch is here and not at the two call
    sites — a caller reaching for `node.elements` on a `bytearray()` would get
    an `AttributeError` on a program the backend can lower.
    """
    if isinstance(node, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        return list_literal_reserved_slots(node)
    if isinstance(node, F.CallExpr):
        ctor = subscript_callee_name(node) or _flat_callee(node)
        if ctor is not None:
            lowering = blob_constructor_lowering(ctor, node.args, node.kwargs)
            if lowering is not None:
                return lowering.elem_count
    return 0


def blob_bytes_reserved(node, list_caps=None, dict_caps=None):
    """How many BYTES `node`'s own construction reserves, or None.

    **None means "not a shape this function sizes", and the one shape it is is a
    nested COMPREHENSION** — because a comprehension's reservation is
    `cap × element size` and `cap` is each backend's own `_compr_cap`, which the
    two architectures compute by different routes (arm64 from the generator's
    literal `range` arguments, x86-64 from its `_blob_est`) and which are NOT
    interchangeable. So the caller asks its own for that one shape and this
    function is the answer for the rest; `None` is the signal, not a zero, and a
    zero would be indistinguishable from an empty blob.

    Both caps tables are passed rather than read from the emitter because both
    are per-FUNCTION state (`_scan_list_caps`'s append-site reservations), and
    the answer has to be an UPPER BOUND: a reservation smaller than the blob it
    is for would make the per-iteration copy below overwrite its neighbour.

    The blob layouts are the emitters' own and are the whole of why this is a
    question at all: `[count:i64][element…]` for a list/set/tuple and
    `[count:i64][key][value]…` for a dict, so a dict literal's bytes are
    `8 × (1 + 2 × pairs)` and not `8 × (1 + pairs)`.
    """
    if isinstance(node, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        slots = max(list_literal_reserved_slots(node),
                    (list_caps or {}).get(id(node), 0))
        return 8 * (1 + slots)
    if isinstance(node, F.DictExpr):
        pairs = max(dict_literal_static_pairs(node),
                    (dict_caps or {}).get(id(node), 0))
        return 8 * (1 + 2 * pairs)
    return None


def blob_nodes_bound_to(fn, name: str) -> list:
    """Every blob-constructing node in `fn` that binds `name`.

    The append-capacity scan's first half (`_scan_list_caps` in each backend):
    `xs.append(v)` needs room the construction does not promise, so the scan
    needs to know what `xs` was built from and how many slots that occupies.

    **It counts a blob CONSTRUCTOR as well as a literal, which is the change
    that makes `bytearray()` growable.** Before this, only a `ListExpr` bound
    the name, so `var b = bytearray()` had no node, `want` was never computed
    for it, and `append` refused with "the receiver is not a list literal this
    function appends to" — a sentence about a LITERAL that was true and
    irrelevant, because the capacity question is about the BLOB and a
    constructor's blob is in the frame on exactly the terms a literal's is.

    One function in the model rather than one per backend: the two copies were
    byte-identical apart from their docstrings, and a shared reader means a
    name both backends agree is bound to a blob is a name both backends reserve
    room for.
    """
    out = []
    body = getattr(fn, "body", None) or []
    for node in iter_nodes(body):
        value = _binding_value(node, name)
        if isinstance(value, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            out.append(value)
        elif isinstance(value, F.CallExpr):
            ctor = subscript_callee_name(value) or _flat_callee(value)
            if ctor is not None and blob_constructor_lowering(
                    ctor, value.args, value.kwargs) is not None:
                out.append(value)
    return out



def dict_lookup_miss_message(base: str, key: str) -> str:
    """Why a dict lookup found no such key — the arm with nothing else to say.

    A bounded stop on this path is supposed to NAME its bound before it stops;
    `_emit_stop_diagnostic` is the shared `write(2)` every one of them uses, and
    `dict_store_overflow_message` / `dict_store_no_room_message` /
    `dict_store_other_blob_message` are the three that answer for a dict STORE.
    A dict READ's miss was the fourth bounded stop with no message, and it is
    the one a program is most likely to take: `d = {"a": 1}` then `d["z"]`
    exits 1 on both architectures with nothing on stdout and nothing on stderr,
    where CPython raises `KeyError: 'z'`.

    Measured on this tree, both backends: that program exits 1 silently.  The
    exit STATUS is the right answer — a lookup that missed has no value to
    invent — but silence makes it indistinguishable from a program that
    crashed, from an assert that failed, and from a divide by zero, and a
    reader of the output cannot tell which.  So this is the sentence for the
    case the three store messages do not cover, which is a base whose capacity
    this build never computed: the STORE arms know the capacity because a store
    is what needed the reservation, and a READ has no reservation to know it by.

    `base` and `key` are the spellings, so the message names the pair the source
    wrote rather than a position.
    """
    return (
        f"KeyError: {key} is not a key of {base}. Python raises `KeyError` for a "
        f"dict lookup that misses, and this path has no value to answer with, "
        f"so it stops here. Measured on this tree, both backends, this case "
        f"exited 1 with nothing on stdout and nothing on stderr, which is "
        f"indistinguishable from an assert, a divide by zero or a crash. Ask "
        f"first — `if k in d:` — or build the pair with a store, which INSERTS "
        f"on a miss the way CPython's `d[k] = v` does")

def dict_walk_mutation_message(what: str, detail: str) -> str:
    """Why a dict's SIZE may not change while a walk over it is running.

    One message for two sites — the `del` that removes a pair and the store
    that INSERTS one — because they are the same rule and CPython raises the
    same `RuntimeError` for both: "dictionary changed size during iteration".
    A store of a key the dict already holds does not change the size and CPython
    permits it, so this is about the INSERT arm only and about `del` at all.

    Measured on this tree, both backends, before the gate:

        d = {"a": 1, "b": 2}
        for k in d:
            del d[k]
        printf("%d\n", len(d))

    answered **1**, exit 0, no diagnostic, where CPython raises
    `RuntimeError: dictionary changed size during iteration`; and

        d = {"a": 1}
        for k in d:
            d["z"] = 5
        printf("%d\n", len(d))

    answered **2** where CPython raises the same `RuntimeError`.  Both are the
    same defect: the walk is an index loop over a count read at run time, so a
    size change under it is not detected by anything, and the program continues
    with a container whose shape the iteration has already lost track of.  The
    `del` row is refused while emitting; the INSERT row cannot be — the miss
    may never happen — so it is a diagnostic and a stop on the arm that
    performs the insert, which is where the question is decidable.

    `what` names the construct ("`del d[k]`" or "`d[k] = v`") and `detail`
    says which arm, so the two sites do not read as one another's sentence.
    """
    return (
        f"RuntimeError: dictionary changed size during iteration. {what} "
        f"{detail}, while a walk over that dict is running, and CPython "
        f"refuses the program there — the walk is an index loop over a count "
        f"read at run time, so a size change under it is detected by nothing "
        f"and the iteration carries on against a container whose shape it has "
        f"already lost track of. Measured on this tree, both backends, before "
        f"this gate: `for k in d:` with `del d[k]` reported 1 where CPython "
        f"raises, and `for k in d:` with `d[\"z\"] = 5` reported 2 where CPython "
        f"raises. Collect the keys first — `ks = []` then `for k in d: ks.append"
        f"(k)` — and delete afterwards, or build a new dict and rebind")


def del_during_walk_refusal(base: str, base_is_dict: bool,
                            walk_depth: int) -> str | None:
    """Why a `del` from a dict may not be emitted inside a container walk.

    The BUILD-TIME half of `dict_walk_mutation_message`, and it is asked from
    `del` rather than from the walk because `del` changes the size
    UNCONDITIONALLY, so whether the program is legal does not depend on
    anything that is only known at run time.  `walk_depth` is the emitter's
    `for … in <blob>` nesting depth; a plain `for k in range(n)` leaves it at
    zero and is not a walk over a container at all.

    A `del` from a LIST inside the walk is deliberately NOT refused: CPython
    permits it, and this path agrees — measured, both backends,
    `a = [1, 2, 3]` then `for x in a: del a[0]` leaves `len(a) == 1` on all
    three, because the list iterator advances by index and a shrink simply ends
    it earlier.
    """
    if walk_depth <= 0 or not base_is_dict:
        return None
    return dict_walk_mutation_message(
        f"`del {base}[…]`", "removes a pair from the dict")


def slice_store_refusal() -> str:
    """Why `xs[a:b] = v` is refused outright on the backend that has no slice
    store at all.

    The WIDER of the two answers to one question.  `slice_store_static_length_
    refusal` beside it answers it for the cases a build can decide, and arm64 —
    which does have a same-length in-place replace — asks that one; this backend
    has no such replace (a slice here is a materialised copy, so writing through
    one would have to write back into its source blob) and so refuses every
    slice store, whatever the lengths.

    One sentence for one reason, in one place, so the two architectures are not
    two answers to the same question.  The measurement is arm64's, and it is
    here because it is the argument against the narrow scope: `a = [3, 1, 2]`
    then `a[0:1] = [9, 9, 9]` built, ran and exited 1 with nothing on stdout and
    nothing on stderr, where CPython answers `[9, 9, 9, 1, 2]` — so a lowering
    that implements half a construct still owes the other half a refusal, and
    the honest place to put it is the build rather than a silent exit.
    """
    return (
        "assignment to a slice target is not lowered on this path: a formal "
        "list blob lives in the frame and cannot change length without a "
        "compaction pass, so `xs[a:b] = v` is only answerable when `v` has no "
        "more elements than the range. Python resizes instead — with "
        "`xs = [3, 1, 2]`, `xs[0:1] = [9, 9, 9]` is `[9, 9, 9, 1, 2]` and "
        "`xs[0:1] = []` is `[1, 2]` — so a slice store that GROWS the length "
        "is a different program from the one this path can emit. arm64 lowers "
        "the same-length case and the SHORTER case; here a slice is a "
        "materialised copy, so writing through one would have to write back "
        "into its source blob")


def slice_store_static_length_refusal(target, value) -> str | None:
    """Why `xs[a:b] = v` cannot be a GROWING store, or None when it can.

    **The one question about a slice STORE that can be answered before anything
    runs, and answering it is the difference between a diagnostic and a silent
    wrong answer.** This path lowers `xs[a:b] = v` as an in-place replace when
    `v` is the same length as the range and as a tail-shift plus count bump
    when `v` is SHORTER — the blob lives in the frame, so a `v` LONGER than
    the range has no room to grow into. CPython resizes: `a = [3, 1, 2];
    a[0:1] = [9, 9, 9]` is `[9, 9, 9, 1, 2]`, and `a[0:1] = []` is `[1, 2]`.
    Measured on this tree, arm64, both of those **exited 1 with no output and
    no message at all** — and that is the worst outcome class there is, because
    the program looks like it ran. x86-64 refuses the whole construct at build
    time with a sentence that names the reason, which is the right answer and
    the wrong SCOPE: a same-length replace is a real lowering, and refusing
    every slice store would take it away.

    So this asks only what is statically decidable, and refuses only then:

    * the receiver is a list/tuple/set LITERAL with no `*` splat, so its count
      is a number this build can see;
    * the bounds are integer literals or absent, and CPython's clamping is
      applied to them the way `_emit_slice_store` applies it (`start` and
      `stop` clamp into `[0, count]`, and `stop` at or below `start` makes an
      empty range);
    * the value is a LITERAL of known length.

    Anything else answers None, which means "this build cannot tell" — not
    "this build is satisfied". The run-time arm is a diagnostic plus `exit(1)`
    rather than a bare exit, so the case this cannot see still says something.
    Both facts are stated in `_emit_slice_store`'s docstring, which is where the
    measurement behind them lives.
    """
    def literal_len(node):
        """`len(node)` when the build can read it, else None."""
        import fire_compiler as F
        if not isinstance(node, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            return None
        if any(isinstance(el, F.UnaryOp) and el.op == "*"
               for el in getattr(node, "elements", []) or []):
            return None
        return len(getattr(node, "elements", []) or [])

    def bound(node, default, count):
        if node is None:
            return default
        value = getattr(node, "value", None)
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        return max(0, min(value, count))

    count = literal_len(getattr(target, "obj", None))
    if count is None:
        return None
    vlen = literal_len(value)
    if vlen is None:
        return None
    start = bound(getattr(target, "start", None), 0, count)
    stop = bound(getattr(target, "stop", None), count, count)
    if start is None or stop is None:
        return None
    if stop <= start:
        stop = start
    if stop - start >= vlen:
        return None
    return (
        f"slice assignment writes {vlen} element(s) over a range of "
        f"{stop - start}, and this path can move the tail DOWN for a SHORTER "
        f"value and replace in place for one of the same length, but a value "
        f"LONGER than the range needs room the blob did not reserve. Python "
        f"resizes instead: with `xs = [3, 1, 2]`, `xs[0:1] = [9, 9, 9]` is "
        f"`[9, 9, 9, 1, 2]` while `xs[0:1] = []` is `[1, 2]`. Measured on this "
        f"tree, arm64 before the gate, both of those exited 1 with no output "
        f"at all, which is a program that looks like it ran. Build the list at "
        f"its final length instead — assign into it, or `append` into a "
        f"literal sized for what the program needs — or split the shift out "
        f"of this line")


def container_membership_refusal(spelled_needle: str, spelled_haystack: str,
                                 needle_kind) -> str | None:
    """Why `needle in haystack` must not be lowered when the NEEDLE is a blob.

    Its OWN function rather than an arm of `container_operator_refusal`, for the
    reason the operator is not in that table either: `in` is ASYMMETRIC. The
    scalar-needle case is a real and correct lowering — `1 in [3, 1, 2]` is a
    linear scan and answers 1 on both backends — and a table keyed on "a blob is
    an operand" would refuse that too. So the question is asked about the needle
    alone, at the membership emitter, on both architectures.

    **A container needle is compared by ADDRESS today, and that is wrong in both
    directions and disagrees between the two architectures.** Measured on this
    tree:

    | program | arm64 | x86-64 | CPython |
    |---|---|---|---|
    | `a = [[1], [2]]`; `1 if [1] in a else 0` | 1 | **0** | 1 |
    | `a = [[1], [2]]`; `b = [1]`; `1 if b in a else 0` | **0** | **0** | 1 |
    | `a = [(1,), (2,)]`; `1 if (1,) in a else 0` | 1 | **0** | 1 |

    Three rows and three different stories.  The first and third are RIGHT on
    arm64 and wrong on x86-64, because arm64's membership emitter decomposes a
    *literal* needle with `static_key_elements` and compares element by element
    while x86-64's compares the needle's base address.  The second is wrong on
    BOTH, because `b = [1]` is a NAME: the literal decomposition does not reach
    it, so the comparison is of two addresses, and `[1]`'s block is not `a[0]`'s
    block.  A row that is right for a literal and wrong for a name is not a
    lowered membership test; it is a coincidence about which address the emitter
    happened to compare, and the two architectures' disagreement on the same
    line of source is the clearest possible statement that neither of them
    answered the question.

    **So this refuses rather than ports arm64's literal path.**  The reasoning
    is `container_operator_refusal`'s and it is the same one: CPython's `in` on
    a container needle is ELEMENT-WISE EQUALITY and then a length check, so it
    needs the same per-element stride.  Porting a special case that happens to be
    right when the needle is a literal of canonical elements — and wrong the
    moment it is a name, a comprehension, or a literal with a computed element —
    would buy the divergence's disappearance at the price of a second
    implementation of an equality this path does not have.

    **What this costs, stated plainly: arm64's literal-needle case answered 1
    and now refuses.**  It is refused on x86-64 already, it was never reachable
    for a name, and the answer it gave was a property of which address the
    emitter compared rather than of the elements — but it is a capability that
    existed on one architecture, and the row above is what it was worth.  The
    dict SUBSCRIPT with a container key is a separate operator and is NOT
    touched here; `d[(1, 2)]` is refused too, by the pre-existing
    `multi_index_refusal_for`, which is a fact about this tree rather than
    something this change took away.
    """
    if not container_operand_is_blob(needle_kind):
        return None
    return (
        f"a container as the NEEDLE of `{spelled_needle} in {spelled_haystack}` "
        f"is refused: this path's membership test compares a blob NEEDLE by its "
        f"ADDRESS, and two blobs holding the same elements are two different "
        f"blocks. Measured on this tree, `a = [[1], [2]]` then `[1] in a` "
        f"answered 1 on arm64 and 0 on x86-64 where CPython answers 1 — and "
        f"`b = [1]` then `b in a` answered 0 on BOTH, because the one case that "
        f"decomposes a literal needle element-wise does not reach a NAME. Python "
        f"compares the needle's ELEMENTS and then its length, so the answer "
        f"needs the same per-element stride `==` does and does not exist here. "
        f"Test membership of the elements instead — write the loop yourself "
        f"with `for x in haystack:` and an element test, which is the same "
        f"question and is answered")


def is_tuple_expr(e) -> bool:
    """True when `e` builds a TUPLE literal or a tuple comprehension.

    The third of the three container-constructor predicates, beside
    `is_dict_expr` and `is_set_expr`, and it exists for the same structural
    reason they do — the value model keeps none of the three, so nothing can
    tell a tuple from a list without one — but for a DIFFERENT question, and
    that difference is what makes it worth having.

    `is_dict_expr` decides whether a subscript means "look this key up" and
    `is_set_expr` whether `|` is a union.  This one decides whether a subscript
    may be WRITTEN AT ALL, because a tuple is IMMUTABLE in CPython: `t = (1, 2,
    3); t[0] = 9` raises `TypeError` there, and a lowering that performs the
    store answers a program CPython rejects.  Measured on this tree, both
    architectures, before the gate: that exact program built, ran, exited 0 and
    printed `t0=9 len=3` — so the mutation happened, silently, where CPython
    refuses to perform it.  That is the worst direction for this backend: the
    program's own later reads then see a tuple that CPython would never have
    produced, and the divergence is not one number but every read of `t` after
    the store.

    The literal half only, as with the other two; a NAME bound to a tuple is
    each backend's `_tuple_vars`, asked from `container_store_refusal`.
    """
    import fire_compiler as F
    if isinstance(e, F.TupleExpr):
        return True
    return (isinstance(e, F.Comprehension)
            and getattr(e, "kind", "list") == "tuple")


def container_store_refusal(spelled_base: str, base_is_tuple: bool,
                            spelled_index=None) -> str | None:
    """Why `xs[i] = v` must not be emitted when `xs` is a TUPLE, or None.

    One function for one question, asked from both backends at the subscript
    STORE — the one site where the answer changes what is emitted rather than
    what is compared.  `is_tuple_expr`'s docstring holds the measurement.

    `spelled_index` is quoted when there is one so the diagnostic names the
    whole write rather than only its base, and a dict subscript is NOT refused
    here: `d[k] = v` reaches a different emitter (`_is_dict_key_subscript`) and
    a dict store is correct, so the caller asks this only on the sequence path.
    """
    if not base_is_tuple:
        return None
    where = f"{spelled_base}[{spelled_index}]" if spelled_index else spelled_base
    return (
        f"{where} is a STORE into a TUPLE, and a tuple is IMMUTABLE in Python: "
        f"`t = (1, 2, 3); t[0] = 9` raises `TypeError: 'tuple' object does not "
        f"support item assignment`. Measured on this tree, both backends before "
        f"this gate, that exact program built, ran, exited 0 and printed "
        f"`t0=9 len=3` — the store HAPPENED, so every later read of `t` in the "
        f"program sees a tuple CPython would never have produced, and the "
        f"divergence is not one number but all of them. A tuple lowers as a "
        f"frame blob here, which is also what a list is, so nothing else in the "
        f"value model can tell the two apart; the refusal is what keeps the "
        f"mutability that CPython's type system guarantees")


def is_set_expr(e) -> bool:
    """True when `e` builds a SET literal or a set COMPREHENSION.

    The twin of `is_dict_expr` above, for the same reason and with the same
    comprehension half: `{x for x in ys}` is a `Comprehension` with
    `kind == "set"`, so a `isinstance(e, F.SetExpr)` test misses it.

    **Set-ness is a question nothing else asked, and the reason it has to be
    asked is that the value model does not keep it.** A set lowers as a list
    (`bugs/formal/FORMAL_set_value_model.md` says so and `container_literal_elem_kind`
    is why: a `SetExpr`, a `ListExpr` and a `DictExpr` all classify as
    `list:<elem>`), so `_blob_vars` holds all three and `ValueKinds` cannot
    tell them apart. The one operator that CAN tell them apart is `|`, because
    Python defines it for exactly two of the three. Measured on this tree,
    arm64, `{"a": 1} | {"b": 2}` reported 1 where CPython reports 2 and
    `{"a": 1, "b": 2} | {"c": 3}` reported 0 where CPython reports 3 — and it
    was NOT the union emitter that answered: this backend's `_is_container_expr`
    does not list `F.DictExpr`, so a dict operand missed the concat/union branch
    altogether and the integer ALU's `ORR` combined two ADDRESSES. Which is the
    same defect `container_operator_refusal` was widened for, reached through
    the one operator that had been left out of it, and it is why the union gate
    is asked beside `string_binary_refusal` where the operand KINDS are known
    rather than at the concat branch. `[1, 2] | [3]` reported 3 where CPython
    raises `TypeError`, and that one DID reach the union emitter, because a list
    literal is a container expression.

    This predicate answers it for a LITERAL. A NAME bound to a set needs the
    flow-sensitive half, which each backend keeps beside `_dict_vars` as
    `_set_vars` and asks through `container_union_refusal` below — the same
    split `is_dict_expr`'s docstring describes, for the same reason.
    """
    import fire_compiler as F
    if isinstance(e, F.SetExpr):
        return True
    return (isinstance(e, F.Comprehension)
            and getattr(e, "kind", "list") == "set")


def container_union_refusal(left: str, right: str, left_is_set: bool,
                            right_is_set: bool, left_is_dict: bool = False,
                            right_is_dict: bool = False) -> str | None:
    """Why `left | right` is not a SET UNION here, or None when it is one.

    The question asked BEFORE the question "does this backend have a union
    emitter", because it is the one that decides whether the emitter would be
    answering the right program at all. Both backends ask it at the same site,
    so a pair of operands cannot get one answer from one architecture and a
    different one from the other.

    Python defines `|` for two kinds and no others:

    | operands | CPython | what this path would emit |
    |---|---|---|
    | `set` OR `set` | union, repeats dropped | **the same thing** |
    | `dict` OR `dict` | a MERGE — the right value wins for a shared key | a union over key/value PAIRS |
    | `list` OR `list` | `TypeError` | a union over list elements |
    | `set` OR `dict` | `TypeError` | whichever the word-level scan made of it |

    so only the first row is a union, and refusing the other three is not a
    missing feature — it is the refusal that keeps a working emitter from
    answering a different program. Measured on this tree, arm64, all three
    wrong shapes: `{"a": 1} | {"b": 2}` reported 1 where CPython reports 2 and
    `{"a": 1, "b": 2} | {"c": 3}` reported 0 where CPython reports 3 — the
    integer ALU's `ORR` on two ADDRESSES, because this backend's
    `_is_container_expr` does not list `F.DictExpr` and a dict operand missed
    the concat branch altogether; and `[1, 2] | [3]` reported 3 where CPython
    raises `TypeError`, which DID reach the union emitter, because a list
    literal is a container expression and its dedup over words is a set
    CPython never built.

    **The message names what the source meant**, because "not supported" sends a
    reader looking for a spec and the spec is the thing that makes the refusal
    honest: a dict pair has to be built by assignment (`d["c"] = 3`, which is a
    lowered dict store, and `d["a"] = 9` correctly overwrites) and a union has to
    be written as a loop over membership tests.
    """
    if left_is_set and right_is_set:
        return None
    if left_is_dict or right_is_dict:
        return (
            f"{left} | {right} is not a SET UNION: `|` between two DICTS is a "
            f"MERGE in Python, where the right-hand value wins for a key both "
            f"sides hold, and this backend has no merge — it lowered the "
            f"operator as a bitwise OR of the two blobs' ADDRESSES, which is "
            f"not a merge and not a union either. Measured on this tree, arm64 "
            f"before the gate: `{{\"a\": 1}} | {{\"b\": 2}}` reported 1 where "
            f"CPython reports 2, and `{{\"a\": 1, \"b\": 2}} | {{\"c\": 3}}` "
            f"reported 0 where CPython reports 3. Build the pair by assignment "
            f"instead — `d[\"c\"] = 3` is a dict store and `d[\"a\"] = 9` "
            f"overwrites the way CPython does — or write the merge as a loop "
            f"over `for k in other:` with a membership test")
    which = ("the left operand" if not left_is_set else
             "the right operand" if not right_is_set else "an operand")
    return (
        f"{left} | {right} is refused because {which} is not established to "
        f"be a SET. `|` is defined in Python for two sets and for two dicts and "
        f"for nothing else — `[1, 2] | [3]` raises `TypeError` there — and "
        f"this path lowers `|` on two containers as a union that deduplicates "
        f"over element WORDS, which is only the right answer when both blobs "
        f"hold elements of one set. Measured on this tree, arm64 with that "
        f"emitter reached for a LIST: `[1, 2] | [3]` reported 3. Use `+` for a "
        f"concatenation, which is what two lists mean here, or build the union "
        f"with an explicit membership test")


def list_repeat_count_refusal(spelled: str, count_spelled: str) -> str:
    """Why `xs * n` is refused because its COUNT is not a compile-time constant.

    The one question about `*` on a container that is not about the frame, and
    the one that has to be asked before the frame question can be: a repetition
    is `len(xs) * n` element slots, so a count this path cannot read at compile
    time makes the RESERVATION meaningless, and a reservation is the only place
    the elements live — there is no heap. Measured: `[0.0] * (m * k)` in
    `test_llm/dumb_gemm.mojo` asks for 4096 slots from a frame whose whole
    container budget is a few kilobytes shared with every other blob in the
    body, so lowering it would either overrun the frame or reserve a guess and
    fail at run time. Both are worse than saying so here, where the reader can
    see the count they wrote.

    `spelled` is the whole expression and `count_spelled` the count operand, so
    the message can name both.
    """
    return (
        f"{spelled} is a REPETITION, and this path can only lower one whose "
        f"count it can read while emitting: the result is len(xs) x n element "
        f"slots in the function's own frame, and there is no heap to grow "
        f"into, so the reservation is made before anything runs and "
        f"{count_spelled} "
        f"is not a number this build can see. Write the count as a literal, or "
        f"build the list at run time (append into a list literal sized for "
        f"what the program needs), or split it across two functions so each "
        f"gets its own budget")


def assignment_target_names(node) -> list:
    """The names one assignment or declaration binds, in source order.

    `x = [1]`, `var x = [1]`, `x: List[Int] = [1]` and `x, y = [1], [2]` are four
    spellings of the same question, and a container check that reads only one of
    them misses the other three silently -- which is the direction this project's
    refusals must never be wrong in. `MultiAssignStmt` is a list of targets and
    the parser records each as a `VarDecl`-shaped node, so both go through here.
    """
    out = []
    name = getattr(node, "name", None)
    if isinstance(name, str) and name:
        # A `VarDecl` records its target as a NAME STRING, not as a node, so the
        # node walk below finds nothing in it. Reading only the node form is how
        # `var xs = []` became invisible to the first version of the container
        # check while `xs = []` was caught.
        return [name]
    targets = getattr(node, "targets", None)
    if targets is None:
        targets = [getattr(node, "target", None)]
    for target in targets or ():
        for sub in iter_nodes(target):
            if isinstance(sub, F.IdentExpr):
                out.append(sub.name)
    return out


def container_escape_sites(fn, returns_container=None, copied=None) -> list:
    """`[(line, what)]` — where a container handed back by a call is read too late.

    **The hazard is not the return. It is the read AFTER another call.**

    A container built in a function's frame does not outlive that function: the
    blob is a block of the frame's own scratch (`_blob_est` in each emitter, and
    the `[count][element]…` shape every container on this path has), and that
    scratch is reclaimed the moment the function returns. Reading the value
    BEFORE the caller makes another call is sound — nothing has been pushed over
    the dead region yet — and reading it after is a use-after-free whose value is
    whatever the next call left there.

    Measured, both architectures, and the two machines give TWO different wrong
    answers for the same source, which is what a use-after-free looks like from
    here:

        def appended() -> List[Int]:
            var xs = []
            xs.append(11); xs.append(22); xs.append(33)
            return xs                    # a frame blob, not a heap one

        def main(n) -> Int:
            var p = appended()
            printf("right after: %d %d %d\\n", p[0], p[1], p[2])  # 11 22 33
            var k = litter(7)            # any call at all
            printf("after: %d %d %d\\n", p[0], p[1], p[2])
            # arm64:  7 8 9      <- litter's own scratch
            # x86-64: 8 9 33     <- a MIX of the two frames

    CPython answers `11 22 33` in both. **A list LITERAL at the return site is
    the same shape and the same wrong answer** (`return [11, 22, 33]`, measured
    identically), which corrects
    `bugs/formal/FORMAL_listdir_no_run_time_sequence.md` item 3: a returned container
    literal is NOT `malloc`'d here, and "it reads correctly immediately after the
    call" is the only reason it looked like it was.

    **Why the check is HERE and not on the return**, and it is the whole design:
    a returned container that the caller reads immediately is sound, and this
    tree has a dozen of those on purpose. `formal/hostmods/struct.mojo`'s
    `unpack_from` is one and its docstring says so ("a list built here is in this
    frame, which is correct for the corpus's immediate `[0]`"), and
    `formal/x86_64_decode.py` reads `struct.unpack_from("<i", code, at)[0]` that
    way. **Refusing the return would refuse a module for a use its own author
    measured as sound**, so the refusal is asked where the fact is: at the READ.

    `returns_container` is `{callee name: True}` for the same-image callees this
    build has decided return a container, and it is what makes the call side
    decidable without a manifest. A call to ANOTHER IMAGE is not here at all:
    `os.listdir` `malloc`s and its docstring says the caller owns it, which is
    why `names = os.listdir(p)`, `names[i]` and `for x in names` work today
    (`test_formal_os_backing.py::listdir_is_a_python_level_list`).

    The scan is over the TOP-LEVEL statements of the body and it is conservative
    in the direction that matters: a call inside a loop or a branch counts as
    happening at the loop's own position, and a name read anywhere after that
    position is refused. `struct.unpack_from(…)[0]` has no binding to be late
    about and is never this shape.

    **`copied` is the set of `id(call)` for the call sites the emitters MOVE into
    the caller's own frame** (`returned_container_blob_bytes` /
    `container_returned_blob_sites`), and a binding whose call is in it is not an
    escape at all: the value the name holds afterwards is a block of THIS
    function's scratch, so the next call cannot reach it. A caller with no such
    table passes nothing and gets the refusal for every one of them, which is
    what a test of the shape alone wants.
    """
    body = getattr(fn, "body", None)
    if not isinstance(body, list) or not returns_container:
        return []
    copied = copied or frozenset()
    params = {name for name, _ann in function_param_shape(fn).fixed}
    # Three index sets over the TOP-LEVEL statements, and the question is
    # whether they INTERLEAVE for one name: a call between a binding and a later
    # read of the same name. That is the whole shape — `struct.unpack_from(…)[0]`
    # has no binding and so no interleaving, and a caller that reads the value
    # before calling anything else has none either.
    bound, reads, calls = {}, {}, set()
    for i, stmt in enumerate(body):
        if isinstance(stmt, (F.AssignStmt, F.VarDecl)) \
                and isinstance(getattr(stmt, "value", None), F.CallExpr):
            callee = call_callee_name(stmt.value.func)
            if callee and returns_container.get(callee) \
                    and id(stmt.value) not in copied:
                # A `VarDecl` records no line of its own, so the CALL's is what
                # the message quotes: same statement, and the one a reader can
                # find.
                line = (getattr(stmt, "line", 0) or 0) \
                    or (getattr(stmt.value, "line", 0) or 0)
                for name in assignment_target_names(stmt):
                    if name not in params:
                        bound.setdefault(name, (i, line))
        for name in _container_reads(stmt):
            reads.setdefault(name, []).append(i)
        # A call ANYWHERE in this statement — a loop body, an `if` arm, a
        # comprehension — counts at the statement's own position.
        if any(isinstance(n, F.CallExpr) for n in iter_nodes(stmt)):
            calls.add(i)
    out = []
    for name, (at, line) in sorted(bound.items()):
        late = [c for c in sorted(calls)
                if at < c and any(r > c for r in reads.get(name, ()))]
        if not late:
            continue
        # The FIRST such call is the one the reader has to look at: everything
        # after it is downstream of the same reclamation.
        first = late[0]
        out.append((_stmt_line(body, first),
                    f"`{name}`, bound at line {line} to a value a function in "
                    f"this image handed back, is read again on line "
                    f"{_stmt_line(body, min(r for r in reads[name] if r > first))}"
                    f", after the call on line "
                    f"{_stmt_line(body, first)} has run"))
    return out


def _container_reads(stmt) -> set:
    """The names a statement READS, as distinct from the ones it binds."""
    bound = set(assignment_target_names(stmt)) \
        if isinstance(stmt, (F.AssignStmt, F.VarDecl)) else set()
    return {n.name for n in iter_nodes(stmt)
            if isinstance(n, F.IdentExpr) and n.name not in bound}


def _stmt_line(body: list, index: int) -> int:
    stmt = body[index] if 0 <= index < len(body) else None
    return (getattr(stmt, "line", 0) or 0) if stmt is not None else 0


def functions_returning_containers(functions: list) -> dict:
    """`{callee name: True}` — this module's own functions that return a container.

    A fixpoint over one question and it is monotone, so it terminates: a
    function returns a container if it returns a list LITERAL, or a NAME it
    binds to one, or a call to a function already known to return one. Nothing
    can stop being a container, so the loop can only grow.

    **This is what makes the escape decidable on the CALLER's side**, and it is
    why the check lives there: the callee's own return is not where the fact is.
    A name in the answer is a function of THIS image, which is what separates it
    from a call to a host module — `os.listdir` `malloc`s and is not refused, and
    the difference is not a judgement about which module is nicer.
    """
    out: dict = {}
    changed = True
    rounds = 0
    while changed and rounds < len(functions) + 2:
        changed = False
        rounds += 1
        for fn in functions:
            name = getattr(fn, "name", None)
            if not name or out.get(name):
                continue
            for node in iter_nodes(getattr(fn, "body", None) or []):
                if not isinstance(node, F.ReturnStmt) or node.value is None:
                    continue
                value = node.value
                hit = isinstance(value, F.ListExpr)
                if isinstance(value, F.CallExpr):
                    callee = call_callee_name(value.func)
                    hit = bool(callee) and out.get(callee) is True
                if not hit and isinstance(value, F.IdentExpr) \
                        and value.name in _locally_bound_containers(fn):
                    hit = True
                if hit:
                    out[name] = True
                    changed = True
                    break
    return out


def _locally_bound_containers(fn) -> set:
    """The names this function binds to a container of its OWN construction."""
    body = getattr(fn, "body", None)
    if not isinstance(body, list):
        return set()
    params = {name for name, _ann in function_param_shape(fn).fixed}
    out = set()
    for node in iter_nodes(body):
        if isinstance(node, (F.AssignStmt, F.VarDecl)):
            if isinstance(getattr(node, "value", None), F.ListExpr):
                out |= {n for n in assignment_target_names(node)}
        elif isinstance(node, F.CallExpr) and isinstance(node.func,
                                                        F.MemberExpr) \
                and isinstance(node.func.obj, F.IdentExpr) \
                and node.func.member == "append" \
                and node.func.obj.name not in params:
            out.add(node.func.obj.name)
    return out


def returned_container_blob_bytes(functions: list, candidates=None) -> dict:
    """`{callee name: nbytes}` — the blob a same-image callee hands back, and
    how many bytes of it a CALLER has to copy to own it.

    **The copy is the whole of this, and it is why the size is a compile-time
    constant rather than the run-time count.** A container this image returns is
    a block of the CALLEE's frame scratch (`_blob_est` in each emitter), and that
    scratch is reclaimed when it returns. The fix the escape refusal names is to
    move the block somewhere the caller owns, and the caller reserves it in its
    own scratch and copies it out immediately after the call — which is sound
    precisely because nothing has been pushed over the dead region yet, so the
    bytes are still the callee's own. After the copy the call's value is the
    CALLER's block, so every later call is irrelevant, which is what makes the
    immediate read and the late read the same program.

    **An OVER-estimate, and that is the safe direction for the two reasons
    there are.** The destination block is sized by this same number, so reading a
    few words past the callee's blob fills words the count word does not reach
    (`[count][element]…` — the count governs how many elements any reader sees),
    and a read of the callee's own frame, or of the caller's above it, is a READ
    and cannot corrupt a live value. An UNDER-estimate would copy the count and
    half the elements and hand the caller a shorter list, which is the wrong
    answer this whole family exists to replace with a refusal. So the capacity
    term is the whole function's append SITES rather than the returned name's,
    which is never smaller and never needs the per-name attribution
    `_scan_list_caps` does in each backend.

    **The three conditions under which there is no answer, and a function with
    none keeps the escape refusal** (`container_escape_sites` is asked with an
    empty `copied`), which is the safe direction for a table:

      * **it does not return on every path** — `returns_on_every_path`, the same
        predicate the returned-FRAME convention decides "may a caller treat this
        function's result as a frame?" with. A function that falls off the end
        leaves whatever was in the return register, and the copy would read from
        it. This is STRICTER than `functions_returning_containers`, which only
        asks whether SOME return is a container, and deliberately so: a set
        membership only decides whether to refuse a read, while a size decides
        where to read `nbytes` from.
      * **some return is not a container of a known size** — a concatenation, a
        comprehension, a slice and a star-splat literal each size their own way
        in the emitters (`_emit_list_concat`, `_emit_list_star`,
        `dynamic_splat_capacity`), so answering for them here would be a second
        answer to a question the emitters own.
      * **a returned NAME is not a blob on every binding** — `xs = []` on one
        path and `xs = 5` on another is one name with two kinds of value, and
        `blob_nodes_bound_to` answers only about the bindings that build a blob.
        Every binding has to be one, which is why this reads the bindings itself
        (`_blob_values_bound_to`) rather than through that helper.
      * **an element is not a plain word** — the copy moves ONE block, and a word
        inside it that is an ADDRESS into the callee's frame does not come with
        it. A returned `List[List[Int]]` would therefore be copied correctly and
        its INNER blobs would still be dead, so `p[0][1]` read late would be a
        wrong answer with a refusal removed in front of it — a worse outcome than
        the refusal, not a better one. `_returned_blob_is_plain_words` is the
        test, and it is a WHITELIST of what is provably a word (`_plain_word`):
        a literal, an operation over literals, or a PARAMETER whose declared
        annotation is a scalar or a string. A local name, a field read and a call
        are all refused, because each of them can be a frame or a blob address
        and telling them apart needs the holder tables this deliberately does not
        read — see that function for the list and for what it costs.

    A fixpoint, and monotone for the same reason `functions_returning_containers`
    is: a name's answer depends on the callees its returns name, and a callee
    that gains an answer can only add bytes. `candidates` narrows the walk to
    the functions `functions_returning_containers` already named, which is what
    keeps this off the hot path of a module with no containers in it at all.
    """
    out: dict = {}
    pool = [fn for fn in (candidates if candidates is not None else functions)
            if getattr(fn, "name", None)]
    changed = True
    rounds = 0
    while changed and rounds < len(pool) + 2:
        changed = False
        rounds += 1
        for fn in pool:
            name = getattr(fn, "name", None)
            if not name or name in out:
                continue
            nbytes = _function_returned_blob_bytes(fn, out)
            if nbytes:
                out[name] = nbytes
                changed = True
    return out


def _function_returned_blob_bytes(fn, table: dict):
    """The bytes `fn` hands back, or None when this path cannot say.

    See `returned_container_blob_bytes` for why each condition is there; the MAX
    over the returns is the same over-estimate the capacity term is, for the same
    reason — the block a caller reserves has to hold the biggest of them.
    """
    body = getattr(fn, "body", None)
    if not isinstance(body, list) or not body:
        return None
    # A nested `def`/`lambda` carries its own `return` statements, and a walk
    # that cannot tell them from this function's would size the outer result by
    # the inner one's value. `_prepare_functions` lifts closures out before this
    # is asked, so a body that still has one has no answer rather than a guess.
    if any(isinstance(n, (F.LambdaExpr, F.FunctionDef))
           for n in iter_nodes(body)):
        return None
    if not returns_on_every_path(body):
        return None
    spare = _append_call_sites(fn)
    words = _plain_word_names(fn)
    sizes = []
    for node in iter_nodes(body):
        if not isinstance(node, F.ReturnStmt):
            continue
        if node.value is None:
            return None
        if not _returned_blob_is_plain_words(fn, node.value, words):
            return None
        nbytes = _returned_blob_bytes(fn, node.value, table, spare)
        if nbytes is None:
            return None
        sizes.append(nbytes)
    return max(sizes) if sizes else None


def _plain_word_names(fn) -> set:
    """The parameters of `fn` whose value is provably a WORD at entry.

    A parameter with no annotation is whatever the caller passed, and this path
    passes a word unless the caller passed a frame — which is the case
    `frame_declared_parameter_refusal` exists for and which the emitters enforce
    per call site. An annotated one is a word only when the annotation is one of
    the scalar or string vocabularies `formal/types.py` publishes
    (`TYPE_NAMES`, `STRING_TYPE_NAMES`, `BOOL_TYPE_NAMES`, `FLOAT_TYPE_NAMES`,
    `DTYPE_TYPE_NAMES`): a `Dict` is a blob and a struct is a frame, so
    `DICT_TYPE_NAMES` is deliberately not among them, and an annotation none of
    the five recognises is not a word either.
    """
    out = set()
    for name, declared in function_param_shape(fn).fixed:
        if declared is None:
            out.add(name)
            continue
        base = _annotation_base_name(declared)
        if base in _PLAIN_WORD_TYPE_NAMES:
            out.add(name)
    return out


def _annotation_base_name(declared):
    """The bare name an annotation's root is spelled, or None.

    `Int`, `List[Int]` and `SIMD[.uint32, 4]` are three spellings of three
    different things and only the first is a scalar word, so the root of the
    annotation is what has to be classified.
    """
    text = declared if isinstance(declared, str) else None
    if text is None:
        return None
    root = text.split("[", 1)[0].strip()
    return root or None


_PLAIN_WORD_LITERALS = (F.IntLiteral, F.FloatLiteral, F.StringLiteral,
                        F.BoolLiteral, F.NoneLiteral)

#: The annotations `_plain_word_names` accepts for a parameter, and the five
#: vocabularies `formal/types.py` publishes rather than a list written here: a
#: fourth copy of "what does this annotation mean" is the one that drifts.
_PLAIN_WORD_TYPE_NAMES = (frozenset(TYPE_NAMES)
                          | STRING_TYPE_NAMES | BOOL_TYPE_NAMES
                          | FLOAT_TYPE_NAMES | DTYPE_TYPE_NAMES)


def _plain_word(value, words: set) -> bool:
    """Whether `value` is a WORD this function computed, not an address it holds.

    The whitelist, and it is deliberately short: a literal, an operation whose
    operands are themselves plain, or a parameter from `_plain_word_names`. That
    covers `[1, 2, 3]`, `[n, n + 1]` and `["a", s]`, which is what the corpus's
    returned containers hold, and it covers nothing else — because a LOCAL name,
    a field read, a subscript and a call can each be a frame or blob address, and
    the tables that would tell them apart (`_frame_holders`,
    `_frame_candidates`, `struct_constructor_sites`) are published on the
    function node by a build pass this deliberately does not depend on, so a
    reader of this predicate gets the same answer with or without one.

    **Refusing here is refusing a capability, not a program.** The escape
    refusal still covers every case this declines, so a container with a nested
    one in it is refused exactly as it was before the copy existed.
    """
    if isinstance(value, _PLAIN_WORD_LITERALS):
        return True
    if isinstance(value, F.UnaryOp):
        return _plain_word(value.operand, words)
    if isinstance(value, F.BinaryOp):
        return (_plain_word(value.left, words)
                and _plain_word(value.right, words))
    if isinstance(value, F.IdentExpr):
        return value.name in words
    return False


def _returned_blob_is_plain_words(fn, value, words: set) -> bool:
    """Whether every word the blob `value` holds is one `_plain_word` accepts.

    Three places a word enters the blob, and all three are asked because missing
    one is the wrong answer this whole family is about:

      * the ELEMENTS of each literal bound to it, for the literal the callee
        returns or the ones a returned NAME is built from;
      * every `append` ARGUMENT — `var xs = []; xs.append(n)` reserves room for
        the append and puts its argument at element 0, so a literal with no
        elements is not a literal with no words;
      * every INDEXED STORE's value, and an in-place `+=`/`*=`/`|=` is refused
        outright rather than reasoned about (`_emit_list_concat` builds a NEW
        blob, so what `xs += ys` leaves bound is a question about the binding,
        not about this one).

    A word copied out of a dead frame is not merely stale: `p[0]` would still
    read the same address and only a DEREFERENCE would be wrong, which is the
    shape a use-after-free takes here and the reason the check is on the elements
    and not on the count.
    """
    if isinstance(value, F.ListExpr):
        nodes = [value]
    elif isinstance(value, F.IdentExpr):
        nodes = _blob_values_bound_to(fn, value.name)
        if nodes is None:
            return False
    else:
        # A call to a callee already in the table: its own return was asked this
        # same question when its answer was computed, so its blob is plain by
        # the same standard and there is nothing to re-check here.
        return True
    for node in nodes:
        if isinstance(node, F.ListExpr):
            if not all(_plain_word(el, words) for el in (node.elements or [])):
                return False
        elif isinstance(node, F.CallExpr) and blob_constructor_lowering(
                subscript_callee_name(node) or _flat_callee(node),
                node.args, node.kwargs) is not None:
            pass
        else:
            # A binding that is neither a literal nor a blob CONSTRUCTOR — `xs
            # = 7`, a slice, a concatenation — so the name is a word on that
            # path and the blob it is returned as has no size.  Asked here rather
            # than left to `_blob_reserved_bytes`, which would hand an
            # `IntLiteral` to `blob_constructor_lowering` and read `.args` off it.
            return False
    if isinstance(value, F.IdentExpr):
        name = value.name
        for node in iter_nodes(getattr(fn, "body", None) or []):
            if isinstance(node, F.AugAssignStmt) \
                    and name in assignment_target_names(node):
                return False
            if isinstance(node, F.CallExpr) \
                    and isinstance(node.func, F.MemberExpr) \
                    and node.func.member == "append" \
                    and isinstance(node.func.obj, F.IdentExpr) \
                    and node.func.obj.name == name:
                if not all(_plain_word(a, words) for a in (node.args or [])):
                    return False
            if isinstance(node, F.AssignStmt) \
                    and isinstance(node.target, F.SubscriptExpr) \
                    and isinstance(node.target.obj, F.IdentExpr) \
                    and node.target.obj.name == name:
                if not _plain_word(node.value, words):
                    return False
    return True


def _append_call_sites(fn) -> int:
    """How many `xs.append(…)` call sites this function has, over every name.

    The over-estimate `returned_container_blob_bytes` uses for the capacity term,
    and it is deliberately NOT `_scan_list_caps`' number: that one is per NAME and
    gates on the name being a list kind, both of which need a value-kind table
    only a backend has, and both of which make the number SMALLER. Small is the
    wrong direction for a size a caller reads `nbytes` from.
    """
    return sum(1 for n in iter_nodes(getattr(fn, "body", None) or [])
               if isinstance(n, F.CallExpr) and isinstance(n.func, F.MemberExpr)
               and n.func.member == "append")


def _blob_values_bound_to(fn, name: str):
    """Every value this function binds `name` to, or None if the name is not
    answerable at all.

    `_binding_value` answers one BINDING SHAPE and misses a `MultiAssignStmt`
    and a valueless declaration, both of which bind a name and neither of which
    builds a blob — so a reader that used it would see one blob binding and miss
    the word the name also holds. `assignment_target_names` is the one answer to
    "does this statement bind this name" whatever the shape, and a statement that
    binds it with no value at all (`var xs` with no initialiser) has no answer
    here either.
    """
    out = []
    for node in iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(node, (F.AssignStmt, F.VarDecl, F.MultiAssignStmt)):
            continue
        if name not in assignment_target_names(node):
            continue
        value = getattr(node, "value", None)
        if value is None:
            return None
        out.append(value)
    return out


def _blob_reserved_bytes(node, spare: int):
    """Bytes the emitters reserve for a blob-constructing NODE, plus `spare`.

    `_emit_list`'s `8 * (1 + cap)` and `_emit_blob_constructor`'s
    `BLOB_HEADER_BYTES + (count + extra_slots) * stride`, read off the same
    helpers the emitters read (`blob_reserved_slots`, `blob_ctor_elem_stride`) so
    the number here and the number reserved there cannot drift. `None` for a
    node neither of those builds — a splat literal goes to `_emit_list_star`,
    whose capacity is `dynamic_splat_capacity` and not the element count.
    """
    if isinstance(node, F.ListExpr):
        if any(isinstance(el, F.UnaryOp) and el.op == "*"
               for el in (node.elements or [])):
            return None
        return 8 * (1 + max(blob_reserved_slots(node), spare))
    if not isinstance(node, F.CallExpr):
        return None
    ctor = subscript_callee_name(node) or _flat_callee(node)
    if ctor is None or blob_constructor_lowering(
            ctor, node.args, node.kwargs) is None:
        return None
    return (BLOB_HEADER_BYTES
            + (blob_reserved_slots(node) + spare) * blob_ctor_elem_stride(ctor))


def _returned_blob_bytes(fn, value, table: dict, spare: int):
    """The bytes the blob `value` is, or None when it is not a sized blob."""
    if isinstance(value, F.ListExpr):
        return _blob_reserved_bytes(value, spare)
    if isinstance(value, F.CallExpr):
        # A blob CONSTRUCTOR first and a plain call second, and the order is the
        # whole of it: `_flat_callee` answers the bare name of BOTH, so asking
        # "is this a constructor?" by name alone sends every ordinary call down
        # the constructor branch, where `blob_constructor_lowering` has no
        # answer and the function is refused — which is how `return g()` lost its
        # answer while `return [1, 2]` kept it.
        ctor = subscript_callee_name(value) or _flat_callee(value)
        if ctor is not None and blob_constructor_lowering(
                ctor, value.args, value.kwargs) is not None:
            return _blob_reserved_bytes(value, spare)
        # `return g()`: the size is g's, not this function's — the block this
        # function hands back is the one IT copied out of g, so the two copies
        # are the same length by construction rather than by agreement.
        name = call_callee_name(value.func)
        return table.get(name) if name else None
    if isinstance(value, F.IdentExpr):
        values = _blob_values_bound_to(fn, value.name)
        if not values:
            return None
        sizes = [_blob_reserved_bytes(v, spare) for v in values]
        return max(sizes) if all(s is not None for s in sizes) else None
    return None


def container_returned_blob_sites(fn, sizes) -> dict:
    """`{id(call): (nbytes, block_offset)}` — the call sites whose result the
    emitters MOVE into this function's own scratch.

    The caller's half of `struct_returned_frame_sites`, and the same shape, with
    BYTES where that one has a struct: a returned frame's block size is a field
    count this function can read off the struct it declared, and a returned
    container's is an element count it has to be TOLD, because the callee is a
    different function (`returned_container_blob_bytes`'s table).

    **EVERY call site gets a block, not only the ones that bind the result**,
    for the reason `struct_returned_frame_sites` gives: a call in a position
    that binds no name still produces a value this function reads immediately
    (`return lit()`, `len(lit())`, `f(lit())`), and the block is what makes that
    read out of the caller's own scratch rather than out of the callee's. The
    cost of covering them is reserved scratch for a result nobody keeps.

    The offset is assigned in walk order, and the emitters put the blocks at the
    bottom of the same reserved region the constructor frames and the
    returned-frame blocks use, so one `_list_cursor` start covers all three and
    the two backends reserve the same bytes at the same offsets.
    """
    if not sizes:
        return {}
    out, offset = {}, 0
    for node in iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.CallExpr):
            continue
        # `call_callee_name`, not `node.func.name`, for the reason
        # `struct_returned_frame_sites` gives: a comptime specialization
        # `lit[T]()` names the same function and emits the same call.
        callee = call_callee_name(node.func)
        if callee is None:
            continue
        nbytes = sizes.get(callee)
        if not nbytes:
            continue
        out[id(node)] = (nbytes, offset)
        offset += nbytes
    return out


def returned_container_refusal(fn, line: int, what: str) -> str:
    """The diagnostic for reading a handed-back container after another call.

    Said at the READ rather than at the return, because that is where the fact
    is: a container this function was handed and reads before it calls anything
    else is sound, and this tree has a dozen of those on purpose
    (`formal/hostmods/struct.mojo`'s own docstring records the shape and the
    measurement). The reader is being told what their program does, not that a
    capability is missing.

    **The last paragraph names the three spellings that lower, and the copy is
    the fourth and is NOT one of them.** A container whose blob has a known size
    and holds only words is copied into this function's own scratch right after
    the call (`model.returned_container_blob_bytes` /
    `container_returned_blob_sites`), so the shape this message is about is one
    the copy declined — a blob of blobs, a callee that does not return on every
    path, a concatenation, or an element that is not provably a word. That is
    why the advice below is about the SOURCE's spelling rather than about the
    copy: none of the three reaches a program this path has no size for.
    """
    who = f"{fn.name}: " if getattr(fn, "name", None) else ""
    return (
        f"{who}{what}. A container built in a function's frame does not outlive "
        f"that function: this path has no heap for a list, so the blob is a "
        f"block of that frame's own scratch ([count][element]… laid out per "
        f"append SITE, `_blob_est` in each emitter), and the scratch is "
        f"reclaimed the moment the function returns. The values read back here "
        f"are whatever this function's NEXT call left in the same stack region "
        f"— measured on both architectures, and the two give two DIFFERENT wrong "
        f"answers for one source (arm64 reads the later call's scratch whole, "
        f"x86-64 reads a mix of the two frames), which is the shape of the "
        f"defect this backend exists to prevent rather than a value anybody can "
        f"check. The shape here is one the CALLER-SIDE COPY declined — "
        f"`model.returned_container_blob_bytes` sizes a blob only when the "
        f"callee returns it on every path, when the result is a literal or a "
        f"blob the callee appends to rather than a concatenation or a splat, "
        f"and when every element is provably a word — so the reader is being "
        f"told which of those four this program is. "
        f"`bugs/formal/FORMAL_listdir_no_run_time_sequence.md` item 3 records "
        f"the capability that closes the rest (a container with a run-time "
        f"length, `malloc`'d rather than frame-resident). What lowers today: "
        f"read the value before calling anything else, keep the container in "
        f"the caller and pass a slot to fill, or take the elements as scalars "
        f"one at a time")


def list_repeat_operands_refusal(left: str, right: str) -> str:
    """Why `a * b` with a container on BOTH sides is refused.

    Python raises `TypeError: can't multiply sequence by non-int of type
    'list'` for every such pair, so there is no program here to answer — and the
    alternative is the one this backend exists to prevent: both words are blob
    addresses, and `mul` of two addresses is a number nowhere near either blob.
    Named rather than lowered so the diagnostic is about the operator.
    """
    return (
        f"{left} * {right} multiplies two containers. Python raises a "
        f"TypeError for that (`can't multiply sequence by non-int`), and on "
        f"this path "
        f"both operands are blob ADDRESSES, so the integer multiply would be a "
        f"product of two pointers rather than a repetition of either. Use `+` "
        f"to concatenate, or `xs * n` with an integer count")


# `diagnostic_byte_length` was a SECOND reader for the same question, landed by
# `work/formal402-docs` in parallel with this one (`work/formal71-docs`), both
# returning the same UTF-8 byte count.  It is deleted by the 2026-10-17 merge:
# one reader is the entire point of this fix, and two of them is exactly the
# "two independent answers to one question" this docstring names.  Nothing
# referred to it but the emitters, which now ask this.


def list_append_overflow_message(name: str, capacity: int) -> str:
    """The ONE text an over-capacity `xs.append(v)` writes to fd 2 before it
    stops the program — for BOTH backends, because two architectures printing
    two different sentences for one limit is how a reader ends up looking for a
    construct one of them invented.

    Why a run-time message at all, when `frame_blob_refusal` above is a
    COMPILE-time refusal: the overflow is not always decidable then. A list's
    capacity is the number of `append` SITES in the function that builds it
    (`_scan_list_caps`), and every EXECUTION of a site counts against it — so
    `while i < 3: xs.append("ab")` is one site run three times, and no pass over
    the source can say it fits. The bound that IS checkable is checked (an
    unrepresentable capacity is refused by name in the emitter), and this
    covers the rest.

    The reason it was silent is the reason this exists. The overflow used to be
    a bare `exit(1)`: no output, no message, nothing on either stream, and a
    program whose only symptom is that it stopped. That is the worst of the
    three possible answers — not a wrong number (which a reader can compare),
    not a named refusal (which a reader can act on), but silence. Every other
    bounded container operation on this path makes the same bargain and every
    other one says which bound it hit.

    No `printf` on this path, so the name and the capacity are spelled into
    the text by the build rather than formatted at run time; `name` is the local
    the receiver resolved to, which is the only thing about the site this path
    knows.

    **The advice was a DEAD END and is rewritten, because a repair that does not
    work is the same defect as a wrong answer with a better costume.** It used
    to read "…or move the appends into a function of their own so the capacity
    each one sees is its own", and the second half does not work:

        def fill() -> List[Int]:
            var ys = []
            var i = 0
            while i < 3:
                ys.append(i)          # overflows HERE, not in main
                i = i + 1
            return ys

    Measured on both architectures: the overflow moves into `fill` and fires with
    the same capacity of 1, because the capacity is counted per FUNCTION and
    moving the appends moves the loop with them. A reader who followed the
    sentence arrived at the identical message with a different function's name on
    it, which is the outcome this message exists to prevent — it is what
    `refuse_none_comparisons`'s own docstring says about a fold that cannot
    observe the difference.

    **What the advice says now is the two spellings that DO work**, and both are
    measured on both architectures rather than reasoned about:

      * build the list with its elements at CONSTRUCTION time — a literal, or
        three `append` SITES outside any loop, which is capacity 3 and computes
        the same thing. The distinction the sentence has to make is SITES versus
        EXECUTIONS, and `while i < 3: xs.append(i)` is one site run three times
        while `xs.append(1); xs.append(2); xs.append(3)` is three sites run once
        each — the same three elements and the same answer;
      * a `for … in range(n)` loop, where the iteration count is a compile-time
        constant, is COUNTED (`model.walk_stmt_trips`), so
        `for i in range(3): xs.append(i)` has capacity 3 and does not overflow.
        That is the one spelling in which a LOOP is the answer rather than the
        cause, and it is worth naming because it is the shape a reader reaches
        for first — a `while` with a literal bound and a `for … in range` over
        the same bound differ here for a reason that is a property of the
        language (`range` has a length this path can read) and not an accident
        of the rewrite.

    What does NOT work, and is therefore absent rather than mentioned: moving the
    appends into another function (measured above), and lowering the capacity so
    the overflow stops — which would be a wrong answer, since the elements past
    the frame's reserve would be written over whatever else is there.
    """
    return (f"formal: list.append overflowed {name!r}: its capacity is "
            f"{capacity}, the number of append SITES in the function that "
            f"built it, and every EXECUTION of a site counts against it — so a "
            f"list built in a loop outgrows the room the frame reserved for it. "
            f"There is no heap on this path, so the blob cannot grow. Two "
            f"spellings compute the same list and fit: build it with its "
            f"elements at construction time (three `append` SITES outside any "
            f"loop is capacity 3, where one site in a loop is capacity 1 "
            f"however many times it runs), or accumulate it in a "
            f"`for … in range(n)` loop whose count is a compile-time constant, "
            f"which is counted rather than capped at one. Moving the appends "
            f"into a function of their own does NOT help: the capacity is "
            f"counted per function, so the overflow follows the appends.")


def blob_growth_overflow_message(what: str, capacity: int) -> str:
    """The ONE text a blob-producing SITE writes to fd 2 when the run-time
    element total exceeds the reservation it made — for BOTH backends, and for
    all three of the sites that make one (`a + b`, `xs * n`, `a | b`).

    **A sibling of `list_append_overflow_message`, not a reuse of it**, and the
    distinction is the fact each one is about. An append's capacity is the
    number of append SITES in the function that built the list; a concatenation,
    a repetition and a union all make a DIFFERENT kind of reservation — a
    static estimate of the element total, multiplied by the loop the site sits
    in (`blob_loop_growth`) and then clamped to the frame's remaining blob
    area. So the sentence has to say THAT, because the reader who is told "the
    number of append SITES" for a `+` has been told a fact about a construct
    that is not the one in front of them, and the advice that follows it
    ("move the appends into a function of their own") does not apply to a `+`
    at all.

    Why a run-time message rather than a compile-time refusal: the reservation
    is an ESTIMATE and the total is read from the two operands' count words, so
    nothing over the source can say they disagree — which is the same reason
    `list_append_overflow_message` exists and is written the same way. Both of
    them used to be a bare `exit(1)`, and both of those were the same defect:
    a program whose only symptom is that it stopped, with no output on either
    stream. Every other bounded container operation on this path makes the same
    bargain and every other one says which bound it hit.

    `what` is the site's own noun phrase — "a list concatenation", "a list
    repetition", "a set union" — which is the word the emitters already pass to
    `frame_blob_refusal` for the COMPILE-time half of the same limit, so the
    two halves of one bound are named the same way. `capacity` is the
    reservation in ELEMENTS, which is the unit the run-time total is counted
    in, so the two numbers in the message are comparable without a conversion
    in the reader's head.
    """
    return (
        f"formal: {what} overflowed its reservation: it reserved room for "
        f"{capacity} element(s) and the run-time element total is larger. "
        f"A blob here is a fixed block of the frame — there is no heap, so "
        f"there is nothing to grow into — and the reservation is an ESTIMATE "
        f"made before anything runs (the operands' lengths are read at run "
        f"time), so it is the estimate that is wrong, not the copy loop. The "
        f"estimate is multiplied by the loop the site sits in, because the "
        f"emitted code is one copy however many times it runs. Build the "
        f"result with its elements known at construction time, or move the "
        f"growth into a function of its own so each one reserves what it "
        f"sees.")


def string_binary_refusal(op: str, left_kind, right_kind,
                          spelled_op: str | None = None,
                          left=None, right=None, fn=None,
                          untyped_callee=None,
                          left_is_set: bool = False,
                          right_is_set: bool = False) -> str | None:
    """The ONE place a binary operator with a string operand is decided not to
    be lowered, so both backends ask the same question in the same order.

    `+`/`+=` first, because that is the one with the measured transcript in it,
    and then everything else that reaches the integer ALU or the flag-setting
    compare. Exists as one entry point rather than two call sites per backend
    precisely because the failure mode being prevented is the two architectures
    disagreeing: the first version of this table was consulted by arm64 and not
    by x86-64 for the augmented forms, so `s += t` printed `[]` on arm64 and
    segfaulted on x86-64 — the same non-answer as `s = s + t`, which both
    backends refused, from the same line of source.

    `left`/`right` are the operand NODES, `fn` the function being emitted and
    `untyped_callee` the backend's "is this a Mojo callee with no declared
    return type".
    Only `string_compare_word_refusal` below uses them — the other arms ask
    about kinds and have no use for the syntax — and they are all OPTIONAL so
    that a caller which has none of them still gets the first two arms. Both
    backends pass all four at every comparison site, so the third arm cannot be
    reached from one site and missed from another: that is the failure this
    function exists to prevent, applied to itself.

    Four arms in the order they are asked, and the order is the order of how
    wrong each would be to get backwards: the untyped-CALL word compare first
    (a `char *` against a `char *`), then `container_relational_refusal` (a blob
    against a blob, where the word is an address), then the string table's three.
    The middle arm is second because it is the only one whose operand is neither
    a string nor a number, and putting it last would have it pre-empted by a
    `string_concat_refusal` that does not apply to it.
    """
    if (left is not None and right is not None and fn is not None
            and untyped_callee is not None):
        word = string_compare_word_refusal(
            op, left_kind, right_kind, left, right, fn, untyped_callee)
        if word is not None:
            return word
    blob = container_operator_refusal(op, left_kind, right_kind,
                                     spelled_op,
                                     left_is_set=left_is_set,
                                     right_is_set=right_is_set)
    if blob is not None:
        return blob
    return (string_concat_refusal(spelled_op or op, left_kind, right_kind)
            or string_arithmetic_refusal(op, left_kind, right_kind,
                                         spelled_op)
            or string_compare_number_refusal(op, left_kind, right_kind,
                                             left, right, spelled_op))


def container_operand_is_blob(kind) -> bool:
    """True when `kind` says the value is a list/tuple/set/dict BLOB.

    One predicate, beside `is_list_kind` and for the reason that one is a
    function rather than a `startswith`: the question "is this word a container
    rather than a number" has three consumers now — this module's relational
    refusal, the emitters' container recognition, and `print`'s own kind
    question — and a name two of them spell differently is a program one of them
    answers by address.
    """
    return is_list_kind(kind)


#: The CPython MEANING of each operator this gate covers, as the message
#: states it.  One table beside the operator set below, because the reason a
#: refusal is honest is that there IS an answer and this path cannot compute
#: it — a reader who is only told "unsupported" goes looking for a spec, and
#: the spec is the sentence that belongs in the diagnostic.  Read off
#: CPython's own operators on `list`/`tuple`/`set`/`dict`, which is what
#: `test_formal_container_methods.py` diffs this path against.
CONTAINER_OP_MEANING = {
    "<": "the first index where the two differ, compared element by element",
    "<=": "the first index where the two differ, compared element by element",
    ">": "the first index where the two differ, compared element by element",
    ">=": "the first index where the two differ, compared element by element",
    "==": "an element-by-element comparison, and then a length check",
    "!=": "an element-by-element comparison, and then a length check",
    "-": "SET DIFFERENCE — every element of the left the right does not hold",
    "&": "INTERSECTION — every element both sides hold",
    "^": "SYMMETRIC DIFFERENCE — every element exactly one side holds",
    "/": "nothing at all: no container in Python has a quotient",
    "//": "nothing at all: no container in Python has a floor quotient",
    "%": "nothing at all: no container in Python has a remainder",
    "**": "nothing at all: no container in Python has a power",
    "<<": "nothing at all: no container in Python has a left shift",
    ">>": "nothing at all: no container in Python has a right shift",
}

#: Every operator this gate covers.  It was the FOUR ORDERING OPERATORS alone
#: until the whole matrix was measured, and every operator missing from it
#: reached either the flag-setting compare or the integer ALU holding a
#: blob's ADDRESS — see `container_operator_refusal`'s transcript for the
#: numbers.  `+` (concatenation), `|` (set union), `*` (repetition), `in`,
#: `not in`, `is` and `is not` are DELIBERATELY ABSENT: each is a real
#: lowering on this path, `is`/`is not` correctly, because two distinct blob
#: literals are two distinct blocks and so two distinct addresses, which is
#: what identity is.  `==`/`!=` on a blob and the ordering operators are the
#: same defect wearing different operators, so they belong in one gate.
#:
#: `-`, `&` and `^` are absent too, and for a reason of their own: they are the
#: three operators whose CPython answer IS a lowering on this path when BOTH
#: operands are SETS.  Set-ness is a flow-sensitive question each backend
#: answers with its own `_set_vars`/`is_set_expr`, so this table — which sees
#: only KINDS — cannot ask it; `container_set_algebra_refusal` below is the gate
#: that does, asked beside this one exactly as `container_union_refusal` is
#: asked for `|`.  They stay in `CONTAINER_OP_MEANING` because that refusal's
#: message quotes the same table.
#:
#: The three operators that are SET ALGEBRA, and the ones a backend may lower
#: once it has a per-element scan: `&` INTERSECTION, `-` DIFFERENCE and `^`
#: SYMMETRIC DIFFERENCE.  They stay in `CONTAINER_OP_MEANING` and are dropped
#: from `CONTAINER_GATED_OPS` below, because for every operand shape EXCEPT two
#: blobs the gate's message is the right answer — but for two BLOBS
#: `container_operator_refusal` DEFERS (returns None) and the backend decides,
#: because whether the pair is a set algebra this path lowers is a fact about
#: the backend and not about the operator.  BOTH backends lower the three for
#: two sets (`_emit_set_op`: arm64's and x86-64's, beside their `_emit_set_union`
#: for `|`), and each refuses a not-two-sets pair by name through
#: `set_algebra_refusal`.  Keeping the gate's message
#: for one-blob operands matters: `[1] & 0` is a CPython `TypeError` and the
#: gate's "is refused when ... is a list" is exactly the right sentence for it.
#:
#: They also cannot simply be absent from `CONTAINER_OP_MEANING`, which is why
#: this paragraph is here rather than folded into the table's own: they are the
#: three operators whose CPython answer IS a lowering on this path when BOTH
#: operands are SETS.  Set-ness is a flow-sensitive question each backend
#: answers with its own `_set_vars`/`is_set_expr`, so a table which sees only
#: KINDS cannot ask it; `container_set_algebra_refusal` below is the gate that
#: does, asked beside `container_operator_refusal` exactly as
#: `container_union_refusal` is asked for `|`.
#:
#: This is the ONE binding of the name, and it is the same tuple the 2026-10-17
#: merge of `work/formal394-docs` found bound three times over in this file (two
#: of them with the members in a different order, so which of them a reader
#: believed the table to have depended on line number).  `test_formal_external_call.py`'s
#: `no_module_level_name_is_bound_twice_in_model` is what pins the count at one.
SET_ALGEBRA_OPS = ("-", "&", "^")
CONTAINER_GATED_OPS = tuple(op for op in CONTAINER_OP_MEANING
                            if op not in SET_ALGEBRA_OPS)


def set_operator_operand_refusal(shown: str, op: str, left_kind,
                                 right_kind) -> str:
    """Why `&`/`^`/`-` is refused when an operand is a blob but NOT both sets.

    `shown` is the operator AS THE SOURCE SPELLED IT (`-=` for the augmented
    form), so the diagnostic names the operator the reader is looking at; `op`
    is the bare operator the meaning table is keyed on.

    CPython defines these three operators for exactly two shapes: two SETS
    (set algebra) and two INTEGERS (bitwise AND, XOR and subtraction).  A pair
    with a container on one side and anything other than a set on the other is
    a `TypeError` there, so there is no correct program to lower — and the
    refusal says that rather than reusing `container_operator_refusal`'s
    per-element-STRIDE sentence, which was written when the two-SET shape had
    no lowering either and is now false about it.
    """
    meaning = {"&": "INTERSECTION (every element both sides hold)",
               "^": "SYMMETRIC DIFFERENCE (every element exactly one side holds)",
               "-": "SET DIFFERENCE (every element of the left the right does "
                    "not hold)"}[op]
    which = ("the left operand" if container_operand_is_blob(left_kind)
             else "the right operand")
    other = ("the right operand" if container_operand_is_blob(left_kind)
             else "the left operand")
    return (
        f"`{shown}` is refused because Python defines it as {meaning} between "
        f"two SETS, or as the integer operation between two integers, and this "
        f"pair is neither: {which} is a container blob (a list, tuple, set or "
        f"dict) and {other} is not a set. CPython raises `TypeError` for this "
        f"source, so there is no correct program to lower. A set here is a list "
        f"blob and the two-SET shape IS lowered on BOTH backends (`_emit_set_op` "
        f"beside their `_emit_set_union` for `|`); write both operands as "
        f"sets, or compare the element you mean")


def container_operator_refusal(op: str, left_kind, right_kind,
                               spelled_op: str | None = None,
                               left_is_set: bool = False,
                               right_is_set: bool = False) -> str | None:
    """Why `a {op} b` must not be lowered when an operand is a BLOB, or None.

    **The wrong answers are measured, and they are WORSE than the ordering ones
    this table started as.**  A blob on this path is a frame-allocated block and
    the word a name holding one carries is its ADDRESS, so every operator here
    is arithmetic on that address rather than on the container.  Measured on this
    tree, both backends, `a = [3, 1, 2]` and `1 if a == [3, 1, 2] else 0` answers
    **0 where CPython answers 1** — `[3, 1, 2]` is a second block at a different
    address, so the equality compares two addresses and says no.  `s = {1, 2}`;
    `t = s - {2}` and `t = s ^ {2}` **SIGSEGV on both architectures** (exit -11,
    no output): the subtraction produces a word far from any blob and `len(t)`
    reads a count out of it.  `t = s & {2}` answers **2 on arm64 and 163061056 on
    x86-64 where CPython answers 1** — one bitwise AND of two addresses, and the
    two architectures' disagreement is the clearest possible statement that
    neither of them computed a set.  `def main(): a = [9]; b = [1]; return len(b)
    if b > a else 0` answers **1 where CPython answers 0**, and the number is the
    ALLOCATION ORDER, not the elements: the same program with the literals the
    other way round (`a = [1, 2]; b = [3, 4]`) happens to agree, because `[3, 4]`
    is the later block and therefore the higher address.

    **The two architectures agreeing is no comfort, and for `==` they do NOT
    agree about being wrong at all**: they agree on the ordering row because they
    lay the frame out the same way, and disagree on the `&` row because their
    `AND` instructions land on different bits of the same two addresses.  Either
    way neither of them compared an element.  That is why this is a refusal and
    not a warning, and it is the outcome class
    `_string_operand_refusal`'s `char *` row already keeps.

    **CPython has an answer for every operator here**, so nothing on the far
    side of this gate is a correct program, and the message says which answer —
    `CONTAINER_OP_MEANING` is the table the sentence is written from, so a
    diagnostic cannot claim a set has no difference while the table says it
    does.  Computing any of them is a loop with a per-element STRIDE, which this
    path would have to know before anything runs; that is a project, not a
    rewrite, and a project is not a reason to answer with an address.  For the
    six operators CPython itself refuses (`/`, `//`, `%`, `**`, `<<`, `>>`) the
    refusal is doubly right: the program is already broken and the diagnostic
    says what it meant to write.

    **The one per-element STRIDE that IS now written is SET ALGEBRA, and it is
    exempted rather than refused.**  `&`, `^` and `-` between two SETS have a
    lowering on BOTH backends (`_emit_set_op`, beside `_emit_set_union` for
    `|`), so when `left_is_set` and `right_is_set` this function returns `None`
    and lets the backend lower it; a site with no whole-set emitter (the
    SUBSCRIPT augmented target) asks `set_algebra_refusal`.  Every OTHER
    blob shape of those three operators is still refused here, by
    `set_operator_operand_refusal` — a LIST `&` list is a CPython `TypeError`,
    not a set.  So the message below reaches only the shapes with no lowering
    and no correct program, which is what keeps its "no lowering to reach for"
    clause true of every program it answers.

    A blob on ONE side is enough: CPython raises `TypeError` for `xs > 0` and for
    `xs == 0` too, so there is no correct program on the far side of this gate.

    `-`, `&` and `^` are NOT in this gate.  Their CPython answer is a real
    lowering when BOTH operands are sets, and set-ness is flow-sensitive, so
    they have their own gate — `container_set_algebra_refusal` below — asked at
    the same site, exactly as `container_union_refusal` is asked for `|`.  The
    numbers quoted above for `s - {2}`, `s ^ {2}` and `s & {2}` are that gate's
    measurements.
    """
    bare = _bare_operator(op, spelled_op)
    if bare not in CONTAINER_GATED_OPS:
        return None
    left_is_blob = container_operand_is_blob(left_kind)
    right_is_blob = container_operand_is_blob(right_kind)
    if not (left_is_blob or right_is_blob):
        return None
    if (bare in SET_ALGEBRA_OPS
            and container_operand_is_blob(left_kind)
            and container_operand_is_blob(right_kind)):
        # Two blobs: whether this is a set algebra THIS BACKEND lowers is a
        # question for the backend (see `SET_ALGEBRA_OPS`), and
        # `set_algebra_refusal` is where a not-two-sets answer is worded.
        # Defer rather than refuse, so each backend can reach its own
        # `_emit_set_op`.  `aug_assign_operands_are_blobs`
        # then routes the augmented spelling through `_emit_binop`, which is
        # the second emitter the desugaring exists for.
        return None
    if bare in ("==", "!="):
        # `==`/`!=` against a NON-blob is a program CPython answers: a blob is
        # never equal to a number or a string, so `[] == 0` is False and
        # `[] != 0` is True whatever the container holds.  The word this path
        # carries for the blob is its block ADDRESS, which is nonzero and not
        # that other value either, so the address comparison gives the same
        # answer — the wrong-answer case the gate exists for is two BLOBS
        # (element-by-element and then a length check), not one.  The ordering
        # operators keep the one-blob rule: `[] < 0` is a `TypeError` in
        # CPython, so there is no correct program on the far side.
        if not (left_is_blob and right_is_blob):
            return None
    on_left = left_is_blob
    which = ("the left operand" if on_left else
             "the right operand" if right_is_blob
             else "an operand")
    # What the DIAGNOSTIC spells, which is not always `op`: the augmented
    # emitters strip the `=` (`>=` arrives as `>`), and a message that told
    # somebody their `>=` was a `>` would be a small lie about the line they are
    # looking at. The same `spelled_op or op` every sibling below uses, and the
    # same reason it cannot just be `op`.
    #
    # **This binding was missing, and its absence was a `NameError` rather than a
    # wrong word**: every program that reached this message got a Python
    # traceback out of the compiler instead of a diagnostic — so `len(max(a, 0))`
    # on `a = [1, 2]` died inside the refusal rather than being refused with one.
    # A diagnostic that cannot be built is the worst of the two answers, and
    # nothing caught it because the arm that raises is only reached by a
    # container operand on one side and one of the gated operators.
    shown = spelled_op or op
    return (
        f"{shown!r} is refused when {which} is a list, tuple, set or dict. A "
        f"blob on this path is a fixed block of the frame, so the word the "
        f"name carries is the block's ADDRESS: `{shown}` is then arithmetic on "
        f"that address and never looks at an element. Measured on this tree, "
        f"both backends: `a = [3, 1, 2]` then `1 if a == [3, 1, 2] else 0` "
        f"answered 0 where CPython answers 1, because the literal is a second "
        f"block at a different address; `s = {{1, 2}}` then `s - {{2}}` and "
        f"`s ^ {{2}}` both died with SIGSEGV and no output, because the result "
        f"is a word nowhere near a blob and `len` read a count out of it; and "
        f"`s & {{2}}` answered 2 on arm64 and 163061056 on x86-64 where CPython "
        f"answers 1, which is one bitwise AND of two addresses — the two "
        f"architectures disagreeing is the clearest sign that neither of them "
        f"computed a set. Python's `{shown}` on two containers is "
        f"{CONTAINER_OP_MEANING[bare]}, and every one of those needs a "
        f"per-element STRIDE this path has to know before anything runs, so "
        f"there is no lowering to reach for. Compare the element you mean "
        f"(`xs[i] {bare} ys[i]`), reduce the pair to the number you actually "
        f"want, or test membership with `in`")


#: The name this gate had while it covered only the four ordering operators.
#: A module attribute rather than a second function, so the two backends, the
#: corpus and the existing callers keep one spelling: a second entry point
#: would be the parallel implementation `CLAUDE.md` rules out, and its name
#: would go on describing four operators out of fourteen.
container_relational_refusal = container_operator_refusal


def set_algebra_refusal(op: str, left: str, right: str, left_is_set: bool,
                        right_is_set: bool, backend_has_emitter: bool) -> str:
    """Why `left {op} right` is not lowered by the backend that asks.

    The SECOND question for `&`/`-`/`^` on two blobs, asked only once
    `container_operator_refusal` has been reached and DEFERRED (it returns
    None for `SET_ALGEBRA_OPS` on two blobs).  There are two answers and the
    caller's `backend_has_emitter` decides which one is true:

    * **not two sets** — Python defines `&`/`-`/`^` (as set algebra) for two
      sets and for nothing else, so `[1] & [2]` is a `TypeError`, and the
      refusal names that rather than pretending a lowering was missing.  This
      is the answer BOTH backends give when they cannot establish both
      operands are sets (each passes `backend_has_emitter=True` at its
      `_emit_binop`, because it does have an emitter for the two-set case).
    * **two sets, no emitter** — the operator really is the set operation the
      source writes, and the machine simply does not lower it.  The message
      says which machine does, so the reader is not sent looking for a spec.
      The one caller left with `backend_has_emitter=False` is a SUBSCRIPT
      target (`a[0] &= b`), where the shape is not two whole sets at all.

    The wording lives here, beside the other refusal texts, so the two backends
    cannot word the same state differently.
    """
    if left_is_set and right_is_set and not backend_has_emitter:
        return (
            f"{left} {op} {right} is a SET operation and this backend has no "
            f"emitter for it: both operands are sets, so Python's `{op}` is "
            f"{CONTAINER_OP_MEANING[_bare_operator(op)]}, and that needs a "
            f"per-element scan this machine does not lower yet. Both backends "
            f"lower `&`, `-` and `^` for two WHOLE sets; this site has no "
            f"whole-set emitter because the operands are element positions, so "
            f"write the operation as a loop over `in` tests instead")
    which = ("the left operand" if not left_is_set else
             "the right operand" if not right_is_set else "an operand")
    return (
        f"{left} {op} {right} is refused because {which} is not established to "
        f"be a SET. Python defines `{op}` as SET ALGEBRA — "
        f"{CONTAINER_OP_MEANING[_bare_operator(op)]} — for two sets and for "
        f"nothing else, so this is a `TypeError` in CPython and there is no "
        f"correct program on the far side of this gate. Compare the elements "
        f"you mean, or build the result with an explicit membership test")


def aug_assign_operands_are_blobs(target_kind, value_kind) -> bool:
    """True when `x OP= y` has a CONTAINER on either side, so it is `x = x OP y`.

    The one question an augmented assignment asks that `_emit_binop` does not
    already ask, and it is asked for the same reason the two backends share
    `string_binary_refusal`: `x += y` is a SECOND emitter, so every fact
    `_emit_binop` knows about `x + y` has to be re-established here or the two
    spellings of one operator answer differently.

    Measured on this tree, both backends, for `a = [1, 2]`:

    | written | this path | CPython |
    |---|---|---|
    | `a + [3]` | 3, both backends | 3 |
    | `a += [3]` | **0 on arm64, SIGSEGV on x86-64** | 3 |
    | `a = a * 3` | 3, both backends | 3 |
    | `a *= 3` | **SIGSEGV on both** | 3 |
    | `s = {1, 2}` then `s` union-assigned `{3}` | 3 on both backends (measured
      before the x86-64 `_emit_set_union` landed; x86-64 refused it by name
      then) | 3 |
    | `s` union-assigned `{3}` | **1 on arm64, 0 on x86-64** (same tree) | 3 |

    which is the whole of it: the binary form is right where it is lowered at
    all, and the augmented form reached the integer ALU holding the receiver's
    ADDRESS.  So the fix is not a new lowering but a DESUGARING — route the
    augmented form through the binary emitter and store what comes back, which
    is what `_emit_binop`'s caller already does for the plain form.  That is why
    this predicate asks about KINDS and lets both backends do the same routing
    rather than each growing its own copy of `_emit_list_concat`.

    The operators with no container lowering are refused by the time a caller
    gets here, because `string_binary_refusal` asks
    `container_operator_refusal` (with the AUGMENTED SPELLING, which this
    module's `_bare_operator` strips) and that gate still refuses every
    container operator except `+`, `|` and — on two blobs — the set-algebra
    three.  `s += t` and `s |= t` desugar here onto the binary emitter; so do
    `s -= t`, `s &= t` and `s ^= t` now that the gate DEFERS the three on two
    blobs, which is what routes them to each backend's `_emit_set_op` rather
    than to the integer ALU.
    """
    return (container_operand_is_blob(target_kind)
            or container_operand_is_blob(value_kind))


def _word_from_an_unannotated_call(fn, operand, untyped_callee) -> bool:
    """True when `operand` is a word whose only provenance is an UNTYPED call.

    The three shapes, and each one is measured:

      * a call result directly — `mk("abc") == other`;
      * a NAME bound from a call in this very function — which is what the
        measured case is, and the reason this function exists rather than an
        `isinstance(operand, F.CallExpr)` test: `c = mk("abc"); d = mk("abc");
        c == d` puts two `IdentExpr` at the `==`, and a syntactic test would
        see two unremarkable names;
      * an ALIAS of such a name — `e = c` — which `_name_bindings` walks, so it
        comes out of the same two cases rather than a third rule.

    A name whose binding CARRIES AN ANNOTATION is not in this set at all, which
    is the fourth shape and the one that keeps the refusal off correct code:
    `var buf: Pointer[UInt8] = fill(p)` binds a name with a declared type from a
    call that declares nothing, and `buf == 0` is a NULL test on a declared
    pointer.

    `untyped_callee(name)` is the backend's answer to "is this a MOJO function
    that does not say what it returns", and the question is asked in the
    backend rather than derived from the kind because `ValueKinds` cannot
    answer it: an unannotated call's result and an `-> int` call's result are
    both `INT_KIND` here, because a word is an integer. The third case matters
    as much as the second — an UNBOUND EXTERN is not this at all.
    `memcmp(a, b, n) == 0` is a comparison of a C library function's return
    value against zero and is correct in every `os` function on this path;
    `getenv(name) == 0` is a NULL check. So the test asks about Mojo callees
    only, and the backend answers it from the parser's `return_type` for a
    function of this image and from the dylib manifest's signature for one in
    another — where an unannotated function's signature return is `void` (see
    `reflect._c_signature`), which is how the two are told apart there.
    """
    if isinstance(operand, F.CallExpr):
        callee = _flat_callee(operand)
        return callee is not None and untyped_callee(callee)
    if isinstance(operand, F.IdentExpr) and fn is not None:
        from_call = False
        for ann, rhs in _name_bindings(fn, operand.name):
            if ann:
                # A DECLARED type, so the name is not an untyped word whatever
                # it was bound from. `var buf: Pointer[UInt8] = fill(p)` is the
                # case that needs this: `fill` says nothing about its return,
                # the local says `Pointer[UInt8]`, and `buf == 0` is a NULL
                # test on a declared pointer rather than a comparison of two
                # words of unknown provenance.
                return False
            if isinstance(rhs, F.CallExpr):
                callee = _flat_callee(rhs)
                if callee is not None and untyped_callee(callee):
                    from_call = True
        return from_call
    return False


def string_compare_word_refusal(op: str, left_kind, right_kind, left, right,
                                fn, untyped_callee) -> str | None:
    """Why `a {op} b` must not be lowered as a comparison of two NUMBERS, or None.

    `FORMAL_string_equality_of_two_unclassified_words`, and the worst
    shape a backend bug can have: a correct program taking the wrong branch,
    silently, on both architectures. `string_comparison_lowering` returns None
    when neither side is a string, and the caller's fallback for None is the
    ordinary integer comparison of two words — so two `char *` into two
    `malloc`'d buffers holding the same four bytes compared UNEQUAL:

        def mk(t):
            var p: Pointer[UInt8] = malloc(64)
            snprintf(p, 64, "%s", t)
            return p

        c = mk("abc"); d = mk("abc")
        c == d                        # FALSE; the answer is TRUE
        strncmp(c, d, strlen(d) + 1)  # 0 — the comparison this is documented
                                      # to lower to, agreeing they are equal

    Three rows localise it exactly. Two interned LITERALS compare equal, so a
    pointer compare would pass. A literal on ONE side makes it a string
    comparison, so `call-lit` is right. And the content compare the code
    documents itself as making says the two are equal. So the content compare
    is not mis-LOWERED — it is never REACHED, because a value that came out of
    a call is classified `INT_KIND` and a word is an integer on this path.

    WHEN IT FIRES, and the narrowness is the design. `==`/`!=` only; neither
    side classified as a string (so this never competes with the content
    compare, which is the right answer); and at least one side a word whose
    only provenance is a call to a MOJO FUNCTION THAT DOES NOT SAY WHAT IT
    RETURNS. Three things that leaves alone, each for a measured reason:

      * an ANNOTATED callee — so `count() == other_count()` for two `-> int`
        functions is untouched, and once `formal/hostmods/os` carries its
        `-> str` / `-> int` annotations (the OTHER half of that bug doc, and
        thirty-odd one-word edits) this stops firing for a path library
        altogether;
      * an UNBOUND EXTERN — `memcmp(a, b, n) == 0` and `getenv(name) == 0` are
        comparisons of a C library function's return value, and they are
        correct on every one of them;
      * two unannotated PARAMETERS — `p == q` on two words from a caller is a
        comparison of two integers far more often than of two strings, and
        refusing it would put a diagnostic in front of correct code;
      * an INTEGER LITERAL on either side — see the comment at the test. The
        measured defect has no literal in it.

    The cost of the narrowness, stated rather than hidden: a function that
    returns a string, says nothing about it, and is called through a name that
    is never bound to a local — `f() == g()` where the result is compared
    directly against another call — is refused, and one compared against a
    PARAMETER is not. The message says exactly what to do about it.
    """
    if op not in ("==", "!="):
        return None
    if string_operand_is_string(left_kind) or string_operand_is_string(right_kind):
        return None
    # A LITERAL on either side is a number, and a comparison against one is a
    # numeric comparison in every case the corpus has. That is not a guess: it
    # is what the two regressions this refusal caused were.
    # `struct Counter: count: Int` with `def get(self): return self.count` and
    # `if c.get() != 37:` has no return annotation to be missing, and a
    # diagnostic in front of it is a diagnostic in front of correct code. The
    # measured defect has NO literal — it is `c == d`, two computed words.
    if isinstance(left, F.IntLiteral) or isinstance(right, F.IntLiteral):
        return None
    if not (_word_from_an_unannotated_call(fn, left, untyped_callee)
            or _word_from_an_unannotated_call(fn, right, untyped_callee)):
        return None
    return (
        f"`{spelled(left)} {op} {spelled(right)}` compares two values this path "
        f"can only call numbers, and at least one of them arrived from a call "
        f"that does not say what it returns. A string on this path is a bare "
        f"`char *` to a `malloc`'d buffer, and two such buffers holding the "
        f"same four bytes are at DIFFERENT addresses, so the comparison this "
        f"lowers to says they are unequal. Measured, on both backends: "
        f"`c = mk(\"abc\")` and `d = mk(\"abc\")` gave `c == d` FALSE while "
        f"`strncmp(c, d, strlen(d) + 1)` returned 0. A correct program takes "
        f"the wrong branch and nothing downstream can tell. The missing thing "
        f"is the CALLEE's return type: annotate it `-> str` or `-> int`, which "
        f"is what puts the answer in the dylib manifest's signature and lets "
        f"this call site classify the result. Until then ask the question with "
        f"the comparison itself — `strncmp(a, b, strlen(b) + 1) == 0` or "
        f"`memcmp(a, b, n) == 0` — which is a real content test and needs no "
        f"kind to be recovered")


def string_unary_refusal(op: str, kind, spelled_operand: str) -> str | None:
    """Why `-s` / `~s` cannot be lowered for a string, or None.

    `-` and `~` are the arithmetic table again with one operand: negation of an
    address and a bit complement of one.  `not` is NOT here any more, and the
    reason it left is the interesting part: it used to be refused because "a
    string is a pointer, and a pointer is never zero, so `not s` is FALSE for
    every string on this path INCLUDING THE EMPTY ONE" — measured, both
    backends:

        s = "abc"
        e = ""
        printf("%d %d", 1 if not s else 0, 1 if not e else 0)   # -> 0 0

    Python's answer is `0 1`. That one was a fabricated FALSITY — a program that
    tests a string for emptiness is told the empty string is non-empty, and no
    downstream check can tell.

    The refusal said so itself and then named the fix: "`_emit_truthy_word` can
    produce the honest answer here too, so the only thing left holding `not`
    back is that the refusal is what a test asserts today".  `not` now goes
    through `truthy_lowering`, the SAME table `if s:` / `while s:` / `s and k`
    already use, so it is `strlen(s) == 0` and not a pointer test — which is
    the same `strlen` the refusal told the reader to write by hand, and the
    empty string is the case that tells a correct lowering from a null test.
    One table, three or four spellings of one question; see
    bugs/formal/FORMAL_string_value_model.md ("found and not fixed").
    """
    if op not in STRING_ARITHMETIC_UNARY_OPS:
        return None
    if not string_operand_is_string(kind):
        return None
    return (
        f"unary {op!r} is refused on a string. A string on this path is a "
        f"bare `char *`, so {op!r} is an integer operation on an ADDRESS, and "
        f"it builds, runs and returns a number the source never wrote — "
        f"`~s` printed 46007208 on arm64 and 38761401 on x86-64 for the same "
        f"source, and those were the ADDRESSES OF THE STRING, because `~` was "
        f"being dropped by the TOKENIZER rather than lowered: `~s` meant `s`. "
        f"`~` on an integer is lowered (`mvn` on arm64, `not` on x86-64), so "
        f"this refusal is about what the operand holds and not about the "
        f"operator. See string_binary_refusal for the two-operand form of this")




# ── truthiness: `if s:`, `while s:`, `a if s else b`, `s and k`, `s or k` ──
#
# `if s:` is not a special case of `if x:`. It is a CONVERSION, and the
# conversion depends on what the operand IS, which is exactly the information a
# CBZ does not have. On this path a string is a bare `char *`, so the identity
# test this table replaces — "is the word nonzero" — says TRUE for every string
# INCLUDING THE EMPTY ONE, because the empty string is a non-null pointer into
# the image's text section. Measured on both backends: `s = "abc"; e = ""`,
# `if s:` and `if e:` both printed `...-truthy`.
#
# The honest test is `strlen(s) != 0`, and it is not a new mechanism: it is the
# same computation `len(s)` already makes with a libc call both backends already
# bind, over the same bytes. So the two cases with a knowable answer are the two
# rows `len_operand_lowering` already has, and this table REUSES those two names
# rather than respelling them — a third spelling of "the length of a string" is
# a third thing to keep in step.
#
# The one kind with no knowable answer here is a FRAME ADDRESS (a struct
# receiver, which is a pointer to a frame of 8-byte slots). Its truthiness is
# pointer truthiness, and that is not a gap: a frame is never mapped at 0, so
# the identity test is the answer. There is no BOOL kind distinct from INT on
# this path — which is why `__mlir_bool__` is refused — so "0/1" and "a bool"
# are the same thing, and both backends' table rows produce a word the
# surrounding code already knows how to read as a boolean.
#
# The compiled path already had this table before the formal path did, in
# `mojo/backend_gimple/emit_stmts.py::_ensure_bool_cond`: a container's length
# for a container, `mojo_truthy_cstr` (a `strlen != 0`) for a `char *`, a
# pointer-nonzero for any other pointer, a nonzero for an integer. Four rows,
# the same four, decided in one place — so this table is the formal path being
# brought into agreement with the compiled one rather than a new decision.
TRUTHY_FROM_STRLEN = LEN_FROM_STRLEN            # `char *`      → strlen(s)
TRUTHY_FROM_BLOB_FIELD = LEN_FROM_BLOB_FIELD    # list/tuple    → its count
TRUTHY_NONZERO = "nonzero"                     # int, frame address, anything
                                                #   else: the word itself
TRUTHY_FLOAT = "float-nonzero"                 # an IEEE double: `x != +0.0`


def truthy_lowering(kind, expr=None) -> str:
    """How "is `expr` truthy" lowers for an operand of kind `kind`.

    A string and a blob both have the same answer, `len(expr) != 0`, because on
    this path truthiness of a container IS its length; every other kind is the
    word itself, and the word's own zeroness is the answer. There is no refusal
    row, and the reason is not leniency: unlike `len()`, an unclassified operand
    is not a case where reading eight bytes at offset 0 invents a number, it is
    a case where the identity test is right for every kind except a string — and
    a string that reaches here unclassified cannot be told apart from a pointer
    by anything this function has. Refusing would turn every `if <unannotated
    name>:` in a codebase that annotates almost nothing into a diagnostic, in
    exchange for closing a hole the kind table has to close (see
    `ValueKinds`, which classifies a `String`-annotated parameter, and the
    flow-sensitive `_string_vars` map, which classifies a local bound to a
    string) rather than a table here.

    `expr` is carried for the same reason `len_operand_lowering` carries it: a
    `range(...)` call classifies as an integer but lowers to a counted blob, so
    `if range(3):` must be FALSE and `if range(0):` must be too, and the answer
    depends on what it lowers to rather than on what the kind says.

    **A FOREIGN-BYTES value is asked here before `len_operand_lowering` and not
    through it**, because it is the one kind for which the two answers differ: a
    `char *` to `""` is a real address and is therefore non-zero, so
    `TRUTHY_NONZERO` would say an empty directory entry is truthy. Its length is
    not answerable as a CHARACTER count (`len_operand_lowering` refuses it, and
    that refusal is right), and truthiness does not need it to be: emptiness is
    the same question on both readings, because a name with zero bytes has zero
    characters and a name with one has one or more. So the answer is `strlen`
    here — the construction, not the count — and that is why this is a separate
    arm rather than a widening of `len_operand_lowering`.
    """
    if kind == POINTER_KIND:
        # A C pointer's truthiness is its own zeroness — the NULL test — and it
        # is asked BEFORE `string_operand_is_string`'s `strlen` for the reason
        # `POINTER_KIND`'s own comment gives: the two agree on a non-empty
        # pointer and disagree on exactly the case the construct exists for, an
        # absent one (`strlen(NULL)`, measured SIGSEGV).  `string_operand_is_
        # string` admits this kind for every OTHER question, so the order here
        # is the whole of the difference.
        return TRUTHY_NONZERO
    if string_operand_is_string(kind):
        return TRUTHY_FROM_STRLEN
    if kind == FLOAT_KIND:
        # A double is the ONE kind for which the word's own zeroness is not the
        # value's zeroness, and it is worth being exact about why, because
        # "the bits are nonzero" is right for almost every double and wrong for
        # exactly one: `-0.0` is the bit pattern 0x8000000000000000, which is
        # nonzero, and CPython says `bool(-0.0)` is False.  Every other value —
        # every nonzero finite double, both infinities, and every NaN — has
        # nonzero bits AND is truthy, so `TRUTHY_NONZERO` would be accidentally
        # right for all of them and observably wrong for signed zero, which is
        # the value a sign-manipulating program produces most often.  So this
        # asks the FP unit: `FCMP` against `+0.0` and the NE reading, which is
        # also what makes a NaN truthy (CPython agrees, and an unordered
        # compare is exactly the "not equal to anything" answer).
        return TRUTHY_FLOAT
    how = len_operand_lowering(kind, expr)
    return how if how is not None else TRUTHY_NONZERO




# ── THE KIND OF A FRAME SLOT, from the DECLARED type of the field ──────────
#
# THE GAP THIS SECTION CLOSES, measured on both architectures before any of it
# existed.  `len` used to be asked "what KIND is this operand" and the answer
# came from one of three places, NONE of which is a declaration:
#
#   * a parameter with no annotation is an INT (a word is an int);
#   * a local bound to a literal takes the literal's kind;
#   * anything else is None, and None is a REFUSAL.
#
# A field read is none of those three, so `self.<field>` classified as None and
# `len(self.<field>)` was refused — with a message that says the source does not
# say what the operand holds, and tells the reader to ANNOTATE IT.  That message
# is false about a declared field, and it was false three ways, once per
# declared type, all on programs that build and print nothing at all:
#
#     struct R:
#         var xs: List[Int]        # len(self.xs)  → "the source does not say"
#         var s:  String           # len(self.s)   → "the source does not say"
#         var n:  Int              # len(self.n)   → "the source does not say"
#
# The first two are not merely badly REFUSED, they are ANSWERABLE and were
# refused: a list field's length is its count field and a `String` field's is a
# `strlen` over its bytes, which is the same two rows `len_operand_lowering`
# already has.  The third is a refusal whose REASON is wrong even as a refusal —
# the source says `Int`, so the integer row is the true one, and a reader sent
# to the annotation paragraph has been told the field is untyped when the
# declaration is two lines above.
#
# So D2's `frame_field_type_candidates` — the agree-or-refuse rule for a
# DECLARED type, which asks exactly this question and answers it with the
# evidence rows every refusal in this file quotes — had no reader on the KIND
# side at all.  It decided where a frame's NESTED bytes live and nothing ever
# asked it what a slot's word HOLDS.  These three functions are that reader.
# Nothing here re-derives the rule: `struct_field_declared_type` and
# `field_type_rows` are D2's, the rule is "use a declared type only when EVERY
# binding agrees, and an absent answer IS the answer", and the third function
# is the one place a caller that has a SET of candidates asks.

# The declared type NAMES this path can turn into a kind, and the decision for
# each.  A name not here yields None rather than a guess, and the shape of the
# refusal is then the same one an unclassified operand gets.
#
# `Dict` is here because `F.DictExpr` already classifies as `LIST_PREFIX` and
# `_emit_dict` already lays the blob out as `[count_pairs][k0][v0]…`: the count
# is the first word for a dict exactly as it is for a list, so leaving a
# DECLARED dict field out would make `len(d)` answerable for a dict literal and
# refused for a dict field, which is a difference in how the field was spelled
# rather than in what it holds.
#
# IT IS NOT REACHABLE FROM A FIELD, and `struct_field_kind` is where that is
# The CONSTRUCTOR names whose value is a blob whose elements are one BYTE each
# (`BYTE_BLOB_ELEM_KIND`), and the only mutable byte sequence in the language.
# `bytes` is deliberately NOT here, and the reason is the REPRESENTATION and
# not the mutability of the spelling: on this path a `bytes` value IS the
# interned `char *` a bytes LITERAL is — measured on both architectures,
# `len(b"abc")` is 3 off `strlen` and `b"abc"[i]` is a one-byte load at offset
# `i` — while `bytes(n)` needs a blob whose SIZE is a runtime value, which is
# the same reservation every other runtime-sized container is refused for.
# `bytearray()` needs no size, and a `bytearray(n)` over a compile-time
# constant `n` needs only what a list literal of `n` words needs, so it is
# admitted and `bytes` is not.
#
# Read by `blob_ctor_elem_stride` (how wide a slot the constructor reserves),
# by `kind_of`'s constructor arm (the KIND the name binds, which is what makes
# `len` read the count and a subscript read one byte), and by both emitters.
# One set for all three, because a constructor that reserved word slots while
# the kind said `byte` would build a blob whose COUNT and whose ELEMENTS
# disagree — the exact defect `bugs/formal/FORMAL_bytearray_and_bytes_have_no_
# representation.md` was filed for.
BYTE_BLOB_CTORS = frozenset({"bytearray"})

# enforced: a container default is refused by `struct_frame_representable`
# ("the default is not a literal"), so a field's slot never holds one of these
# on this path.  The name is kept because it is the vocabulary the same
# question asks elsewhere — a `var xs: List[Int]` ANNOTATION is a real
# declaration of what the slot is FOR, and the refusal below quotes it.
#
# `BYTE_BLOB_CTORS` is UNIONED rather than written in, so the set of names that
# build a counted region and the set of names that build a counted region OF
# BYTES cannot drift: the first is the annotation question and the second is
# the element width of what the first builds.
BLOB_TYPE_CTORS = frozenset({
    "List", "list", "Tuple", "tuple", "Set", "set", "Dict", "dict",
}) | BYTE_BLOB_CTORS


def frame_slot_value_refusal(spelled: str, ann, slot_kind) -> str | None:
    """Why a FRAME SLOT's declared type is not enough to answer `len`, or None.

    The fourth row `len_refusal` can be asked for, and the one this whole
    section exists to supply.  A field read whose declared type this path
    recognises still cannot be lowered, and the reason is a property of the
    CONSTRUCTOR rather than of the annotation: `S()` does not run `__init__`
    (premise (B2)), so a fresh instance's slot holds the class-level default,
    and a field with no class-level default is a word of zeros.  For a container
    that means the count word `len` wants to read is at address 0; for a string
    it means libc would be asked to walk the bytes at address 0.

    Measured, on both architectures, with the kind claimed from the annotation
    alone and nothing else changed:

        struct R:
            var xs: List[Int]
            var n: Int
            def size(self) -> Int:
                return len(self.xs)
        def main(k: Int) -> Int:
            var r = R()          # __init__ would have put a list here
            return r.size()

    built, ran, and died with **SIGSEGV (exit 139)** — `LDR X0, [X0]` with X0
    zero.  The `var s: String` spelling of the same shape died the same way,
    through `strlen`.  A crash rather than a wrong number, which is the good
    half of the outcome and not the whole of it: the build stayed green and the
    emitted code dereferenced a null pointer, so nothing downstream could have
    told.

    So the answer is a refusal, and the reason names the premise rather than
    the annotation — the annotation is fine, and `len(self.xs)` is exactly the
    right thing to write.  What is missing is a VALUE in the slot, and the ways
    to put one there are spelled out because each is the same program with a
    representation.

    The INTEGER spelling gets its own sentence and not this one, because there
    the missing value is not what makes `len` unanswerable — an integer has no
    length either way — so the row that applies is the integer row, and the
    only thing this adds to it is that the number in the slot is the default
    rather than what `__init__` assigns.  That is a true statement about a
    program whose premise is already broken, and it says so rather than
    implying the annotation was the problem.
    """
    if not isinstance(ann, str) or not ann.strip():
        return None
    if is_list_kind(slot_kind):
        return _frame_slot_blob_refusal(spelled, ann)
    if string_operand_is_string(slot_kind):
        return _frame_slot_string_refusal(spelled, ann)
    if slot_kind == INT_KIND:
        return _frame_slot_int_refusal(spelled, ann)
    if slot_kind == TYPE_KIND:
        # The fourth row, and it is the shortest of the four because the slot's
        # MISSING VALUE is not what makes `len` unanswerable here either: a type
        # tag is one word and has no count at offset 0 whatever it holds. So the
        # type row is the operative one and this adds the same one fact the
        # integer row adds -- the word in the slot is the class-level default,
        # not what `__init__` assigns -- for a field whose declared type says
        # the word is a TYPE. Without this row the kind fell through to `None`
        # and the reader got the unclassified "the source does not say what this
        # operand holds" about a field whose declaration says `DType`.
        return (
            f"len({spelled}) — this slot's DECLARED type is {ann!r}, and on "
            f"this path a type in a value position is one 64-bit TAG (a hash of "
            f"the type's name), which has no count at offset 0 and no length at "
            f"all. A type is not a string and not a container, so there is no "
            f"length of it to ask for. As with the integer row, the number in "
            f"the slot is the class-level default rather than what `__init__` "
            f"assigns: `S()` does not run `__init__` on this path (premise "
            f"{FRAME_FIELD_BLOB_PREMISE_B2})")
    return None


def _frame_slot_int_refusal(spelled: str, ann) -> str:
    """`frame_slot_value_refusal`'s integer row: right answer, no missing value.

    The only one of the three where the missing VALUE is not what stops the
    lowering — an integer has no length whether the slot holds 7 or 0 — so the
    integer row is the operative one and this adds the one fact that row cannot
    know, which is that the number in the slot is the class-level default rather
    than what `__init__` assigns.  That matters because it is what a reader
    would otherwise conclude: `len(self.n)` saying "an integer has no length"
    about a field declared `n: Int` is true AND complete as far as `len` goes,
    but the annotation paragraph it used to be preceded by ("annotate it") is
    what sent people to a field that is already annotated.
    """
    return (
        f"len({spelled}) — this slot's DECLARED type is {ann!r}, and an integer "
        f"has no length: there is no count to read at offset 0, and the word "
        f"there is the integer itself. Worth knowing alongside that, because it "
        f"is not what the declaration says the number is: `S()` does not run "
        f"`__init__` on this path (premise {FRAME_FIELD_BLOB_PREMISE_B2}), so a "
        f"fresh instance's slot holds the class-level default, and a field with "
        f"no class-level default is a word of zeros")


def _frame_slot_blob_refusal(spelled: str, ann) -> str:
    """`frame_slot_value_refusal`'s container row. See that function.

    The count word is at offset 0 of the blob, so the failure this row replaces
    is a load through a null pointer: eight bytes read from address 0 and called
    a length.
    """
    return (
        f"len({spelled}) — this slot's DECLARED type is {ann!r}, so the "
        f"lowering is settled: a list's length is the count word at offset 0 "
        f"of its blob. What is missing is the VALUE. `S()` does not run "
        f"`__init__` on this path (premise {FRAME_FIELD_BLOB_PREMISE_B2}), so a "
        f"fresh instance's slot holds the class-level default, and a field with "
        f"no class-level default is a word of zeros: the count word would be "
        f"read from address 0. Measured with the kind taken from the "
        f"declaration anyway, on BOTH architectures: this built, ran, and died "
        f"with SIGSEGV (exit 139). A container default is refused "
        f"separately and by name (`struct_frame_representable`: the default is "
        f"not a literal), so there is no way to reach the value from the "
        f"declaration in either direction. Give the slot a value a running "
        f"statement puts there — build the list in the caller and assign the "
        f"field after `S()` — or take the list as a parameter, which is the "
        f"same program with a lifetime this analysis can see")


def _frame_slot_string_refusal(spelled: str, ann) -> str:
    """`frame_slot_value_refusal`'s string row, and a DIFFERENT failure.

    The same premise (B2) and the same missing value, and not the same wrong
    answer: `strlen` over a null pointer does not read eight bytes and call them
    a count, it walks the bytes at address 0 looking for a terminator that is
    not there.  So the emitted instruction is a `BL _strlen` and the fault is
    inside libc, one frame deeper than the container row's `LDR X0, [X0]` —
    which is why the two are named separately rather than sharing a sentence
    that would have to be true of both.

    Measured on both architectures with the kind taken from the declaration
    alone: `var s: String` with the value assigned in `__init__`, and
    `len(self.s)` inside a method, built, ran, and died with SIGSEGV (exit
    139).
    """
    return (
        f"len({spelled}) — this slot's DECLARED type is {ann!r}, so the "
        f"lowering is settled: a string's length is a `strlen` over its bytes "
        f"to the NUL. What is missing is the VALUE. `S()` does not run "
        f"`__init__` on this path (premise {FRAME_FIELD_BLOB_PREMISE_B2}), so a "
        f"fresh instance's slot holds the class-level default, and a field with "
        f"no class-level default is a word of zeros: libc would walk the bytes "
        f"at address 0 looking for a terminator. Measured with the kind taken "
        f"from the declaration anyway, on BOTH architectures: this built, ran, "
        f"and died with SIGSEGV (exit 139), inside the `strlen`. A field with a "
        f"LITERAL default is answered rather than refused — `var s: String = "
        f"\"hi\"`, which the constructor materializes at every site — so the "
        f"declaration is not what is missing here. Give the slot a value a "
        f"running statement puts there, or take the string as a parameter, "
        f"which is the same program with a lifetime this analysis can see")


def declared_type_kind(ann, int_names=(), string_names=(), decls=None,
                       bool_names=(), dtype_names=(), float_names=()):
    """The kind a DECLARED type annotation gives, or None for one we cannot map.

    The one question `struct_field_kind` and its callers ask, and it is
    deliberately narrow: it maps a type NAME this path has a representation for
    and returns None for everything else, so a name it has never heard of
    produces the pre-existing unclassified refusal rather than a new one.

    `int_names` / `string_names` are the backend's annotation vocabularies
    (`formal.types.TYPE_NAMES` / `STRING_TYPE_NAMES`) rather than constants
    here, for the reason every other shared table in this file takes them from
    the caller: the two backends must not answer this question from two private
    lists, and a name is a string, not a representation.

    `dtype_names` is the fourth vocabulary and it is NOT a kind of its own: a
    value annotated `DType` holds a TYPE TAG, which is `TYPE_KIND` — the same
    kind a local bound to `DType.int32` already has (`ValueKinds.name_kind`
    returns it for a name no local and no module global binds). Without this
    row the same word had two kinds depending on where the name was written: a
    `var d: DType` FIELD was unclassified, so `len(self.d)`, `self.d[i]` and
    `print(self.d)` were all refused by the machinery that refuses a word whose
    kind nothing states, while `t = DType.int32` in a local answered. The
    refused pair is refused either way and only with a different sentence; the
    widening is `print(self.d)`, which now prints the tag as the number it is —
    the same widening the construct already made for a local, so leaving the
    field spelling refused would have been the inconsistency.

    A separate argument, and NOT defaulted to `formal.types.DTYPE_TYPE_NAMES`
    here, for the reason the two above are not: this module deliberately does
    not import `formal.types` (`STRING_TYPE_CTORS`' own comment), and a default
    would give this function a fourth answer its model-internal callers do not
    pass — `one_word_value_text_evidence` and `dylib_export_return_kind` ask
    "is this holder / this export a TEXT value", where a type tag is not text
    and both already answer `None` for want of a vocabulary.

    `float_names` is the FIFTH vocabulary and it DOES produce a kind of its own,
    `FLOAT_KIND` — the first new one since `TYPE_KIND`, and the reason it is a
    separate argument rather than another row of `int_names` is that a `double`
    is a word that must NOT be read as an integer: `is_number_kind` has to say
    no for it, or `%d` renders a double's exponent field as a decimal, and
    every arithmetic site has to know it is looking at a pattern rather than a
    value.  See `FLOAT_KIND` for the measurement that a `FloatLiteral` reading
    as `INT_KIND` built and answered `0` where CPython answers `3.75`.

    `bool_names` is the THIRD vocabulary and it does not produce a kind of its
    own: a `Bool` on this path is a word holding 0 or 1, so its kind IS
    `INT_KIND` — which is what `_kind_of_simple` already says about a
    `BoolLiteral`, and putting `Bool` in `int_names` would say the same thing
    one line earlier. It is a separate argument because ONE caller needs the
    narrower fact as well ("this word is 0 or 1, so `x != 0` is its value"),
    and a kind cannot carry it: every consumer of `INT_KIND` would have to learn
    to ask, and the ones that must not — a `%s` format, a `len` — would get a
    second opinion to keep consistent. See `annotation_is_bool` for the reader.

    `decls` is `{name: StructDef}` for the structs THIS MODULE DECLARES, and it
    is what turns one declared type into `FRAME_KIND`: a slot annotated with a
    struct of this module whose receiver is a frame holds that struct's ADDRESS,
    which is a different word from every other value on this path and gets its
    own row in `len_refusal` and its own answer in `truthy_lowering`.  Without
    `decls` the same annotation is None, which is the conservative direction —
    the unclassified refusal — and is why every caller that can pass it does.

    ORDER matters and is the whole of the function: a string is checked before
    a blob, because `STRING_TYPE_NAMES` and `BLOB_TYPE_CTORS` are disjoint
    today and if they ever were not, `String` is the answer that is right.  The
    struct check comes after the scalars and before the blob row, because a
    struct of this module is a type this image can PLACE, so a framed one is a
    fact about the value in the slot rather than about the slot's annotation.
    """
    if not isinstance(ann, str) or not ann.strip():
        return None
    base = annotation_base_name(ann)
    if base is None:
        return None
    if base in string_names:
        return STR_KIND
    if base in float_names:
        return FLOAT_KIND
    if base in bool_names:
        return INT_KIND
    if base in int_names:
        return INT_KIND
    if base in dtype_names:
        return TYPE_KIND
    if decls is not None:
        inner = structs_declared(base, decls)
        if inner is not None and struct_is_framed(inner):
            return FRAME_KIND
    if base in BYTE_BLOB_CTORS:
        # A DECLARED `bytearray` says the slot holds a byte blob, so it says
        # the element width as well — and it is the same answer the
        # CONSTRUCTOR gives (`kind_of`'s constructor arm), which is the point:
        # `var b = bytearray(3)` and `var b: bytearray = bytearray(3)` have to
        # be one kind or the emitter reads one layout and `len` another.
        return byte_blob_kind()
    if base in BLOB_TYPE_CTORS:
        return list_kind(None)
    return None


def declared_type_is_dict(ann, dict_names=("Dict", "dict")) -> bool:
    """Whether a DECLARED type annotation says the value is a DICT.

    The one question `declared_type_kind` deliberately does not answer, and why
    it cannot: on this path `List[Int]`, `Tuple[Int, Int]`, `Set[Int]` and
    `Dict[String, Int]` are all ONE word pointing at a blob with an 8-byte count
    header, so `declared_type_kind` maps every one of them to the bare list
    prefix — correctly, for every question that asks "how wide is an element",
    and wrongly for the one that asks "does a subscript with a string index mean
    a key lookup". Two questions, two pieces of evidence, and the second was
    missing: `d["a"]` on a `Dict[String, Int]` PARAMETER took the sequence
    subscript, because nothing had ever said the base was a dict
    (`“FORMAL_container_from_a_call_has_no_shape_so_a_string_subscript_faults”`).

    So this is deliberately NOT a wider `declared_type_kind`: that function's
    table maps a type to a REPRESENTATION and every row in it is true for both
    containers, while this one maps a type to a SPELLING of a subscript. Merging
    them would have to make one of the two answers wrong.

    `dict_names` is the caller's vocabulary (`formal.types.DICT_TYPE_NAMES`),
    for the same reason every other shared table here takes it from the caller:
    a name is a string, and the two backends must not answer this from two
    private lists.
    """
    if not isinstance(ann, str) or not ann.strip():
        return False
    base = annotation_base_name(ann)
    return base is not None and base in dict_names



def annotation_is_bool(ann, bool_names=()) -> bool:
    """Does this declared type say the word holds 0 or 1?

    NOT `declared_type_kind(ann) == INT_KIND` and deliberately not: a kind says
    what a value IS, and both an `Int` and a `Bool` are `INT_KIND` on this path
    (a Bool is a word holding 0 or 1, and `formal.types.BOOL_TYPE_NAMES`' own
    comment is the argument). What `pop.select` needs is the narrower fact —
    "is this 0 or 1" — because that is what makes `x != 0` the right lowering of
    `x.__mlir_bool__()` rather than a `char *`'s "is this address non-zero", and
    the two programs differ only in the declaration.

    So the vocabulary is passed in for the reason `declared_type_kind` takes
    its own from the caller: one reader of "what does this annotation mean",
    so the two cannot answer differently about `condition: Bool`.
    """
    if not isinstance(ann, str) or not bool_names:
        return False
    base = annotation_base_name(ann)
    return base is not None and base in bool_names


def struct_field_kind(struct_def, name, int_names=(), string_names=(),
                      decls=None, dtype_names=(), float_names=()):
    """The kind `struct_def`'s field `name` HOLDS, or None when it does not say.

    One `StructDef`, so there is no agreement to check: the declaration is the
    declaration.  The agree-or-refuse is `frame_slot_field_kind` below, which is
    the same question asked of a name that might be two different structs.

    THE GATE, and it is the whole of what makes this safe: a field's ANNOTATION
    is a fact about its type, while the word in its slot is a fact about the
    constructor, and on this path the two come apart.  `S()` does not run
    `__init__` (premise (B2), `FRAME_FIELD_BLOB_PREMISE_B2`), so a fresh
    instance's slot holds the class-level DEFAULT, not what the struct's own
    constructor assigns — and a field with no class-level default at all is a
    word of zeros.  So a kind is returned only when the slot's value is
    something this path actually materializes:

      * a LITERAL class-level default, which `struct_field_default` reports as
        `DEFAULT_INT` / `DEFAULT_STRING` and the constructor stores at every
        site.  Measured on both architectures: `var s: String = "hello"` gives
        `len(self.s) == 5` and `var n: Int = 7` gives `self.n == 7`, both
        correct;
      * a NESTED FRAMED STRUCT, which the constructor PLACES — see
        `struct_nested_frame_fields` — so the slot holds a real frame address
        whatever the defaults are;
      * a value a CONSTRUCTOR puts there — `ctor_establishes_slot` below, and
        the door the other two could never open, because a container has no
        literal class-level default on this path.

    Everything else is None, and None is the answer rather than a gap in the
    table.  It is what `len(self.xs)` gets for `var xs: List[Int]` when nothing
    puts a list in the slot, and the reason refusing is right is measured, not
    inferred: with the kind claimed from the annotation alone, the same program
    BUILT on both architectures and died with SIGSEGV (exit 139), because the
    slot held 0 and `len` loaded eight bytes from address 0.  A container
    default is already refused by name — `struct_frame_representable` says "the
    default is not a literal" — so the value is unreachable from the
    DECLARATION in every direction, and `frame_slot_value_refusal` is what says
    so.  It is reachable from the CONSTRUCTOR, which is the third door.
    """
    base, ann, _ev, _why = struct_field_type(struct_def, name, decls)
    if base is None:
        return None
    kind = declared_type_kind(ann, int_names, string_names, decls,
                              dtype_names=dtype_names,
                              float_names=float_names)
    if kind is None or kind == FRAME_KIND:
        return kind
    default, _payload = struct_field_default(struct_def, name)
    if default in (DEFAULT_INT, DEFAULT_STRING):
        return kind
    if ctor_establishes_slot(struct_def, name, kind):
        return kind
    return None


def ctor_establishes_slot(struct_def, field: str, kind: str) -> bool:
    """Do this struct's CONSTRUCTORS put a value of `kind` in `field`?

    The third door of `struct_field_kind`, and the one that exists because a
    container cannot come in through the other two: this path materializes a
    container default only as `[]`, and a field declared `var xs: List[Int]` with
    `= []` is not a program the standard library writes — the shape is a
    constructor that BUILDS the container.

    **`S()` does run `__init__`, which is what used to be the premise here and
    is not the question any more.** The lowering inlines the body at the
    construction site (`init_body_stores`), so a value the constructor assigns is
    a value the object HAS, at every site, in every function.  So the evidence
    is the constructor's own store, and four conditions have to hold together:

      * the struct is ONE FIELD (`struct_is_one_field`), so its receiver IS
        this field.  That is not tidiness: premise (B1) —
        `FRAME_FIELD_BLOB_PREMISE_B1`, "no executed method writes a container
        into a field" — is about a container whose lifetime is the ASSIGNING
        function's while the slot's lifetime is the object's, and a multi-field
        struct's frame is exactly the object whose lifetime outlives the
        assigning function.  A one-field struct has no frame at all: the word
        IS the container address, and its lifetime is the ordinary value path's,
        which already governs every `var xs = List[Int]()` in the corpus.  This
        is the same line `formal/build.py`'s `check_frame_field_container_writes`
        draws, for the same reason.
      * the struct DECLARES a constructor, and every one of them assigns this
        field.  A constructor that leaves it alone leaves the class-level
        default there instead, which for a container is the unrepresentable
        case the first two doors refuse.
      * every such store is a value this path MATERIALIZES as `kind`: a
        container display (`[]`, `[1, 2]`) or a zero-operand construction of an
        empty container (`List[Int]()`, `Dict()`), which are `_emit_list` and
        `_emit_empty_blob` respectively — the same two blob layouts `len` reads
        a count out of.  A store this path cannot evaluate is the absent answer,
        and `List[Int](capacity=n)` is one, because a blob that must HOLD n
        elements needs a reservation sized by a value this compiler has not at
        layout time.
      * no method OTHER THAN `__init__` writes the field
        (`struct_field_written_outside_init`), because `ValueKinds` is
        flow-insensitive by construction and a setter would put something else
        in the slot with the constructor saying nothing about it.

    The BODY shape is read through `_init_statement_field_stores`, the same
    table `init_body_stores` inlines from, so this cannot claim a value out of a
    statement the emitter is going to refuse; and `_init_free_names` is the
    emitter's own rule about names, so a right-hand side that needs a binding
    the construction site does not have is refused before this is asked.  The
    two are not re-derived here and that is the point: a third copy of either
    question is a third answer.

    **What it does not cover, stated because it is the residual and not a
    detail.** The claim is about the CONSTRUCTOR, so it is a claim about every
    way a value of this struct comes into existence being a construction.  A
    value that arrives without one — a bare `var w: W` that is never assigned —
    is not something this analysis can rule out at the use site, and a program
    that does that and then asks for its `len` still faults.  It is the same
    residual the LITERAL-default door has for a field whose value a later
    statement overwrites (`a_field_written_after_its_construction_is_refused` is
    the per-site half of it), and it is refused rather than guessed because the
    wrong answer is a load from address 0.
    """
    if kind is None or not is_list_kind(kind):
        return False
    if not struct_is_one_field(struct_def):
        return False
    if struct_field_written_outside_init(struct_def, field):
        return False
    receivers = struct_receivers(struct_def)
    saw_ctor = False
    for method in struct_methods(struct_def):
        if method.name != "__init__":
            continue
        saw_ctor = True
        stores = []
        for stmt in (getattr(method, "body", None) or []):
            if isinstance(stmt, F.PassStmt):
                continue
            if isinstance(stmt, F.ExprStmt) and isinstance(stmt.value,
                                                          F.StringLiteral):
                continue        # a docstring is a statement with no effect
            if not isinstance(stmt, F.AssignStmt):
                return False    # a body `init_body_stores` would refuse
            pairs = _init_statement_field_stores(stmt, receivers)
            if not pairs:
                return False
            stores.extend(pairs)
        mine = [value for target, value in stores
                if isinstance(target, F.MemberExpr) and target.member == field]
        if not mine or not all(_value_materializes_blob(v) for v in mine):
            return False
    return saw_ctor


def _value_materializes_blob(value) -> bool:
    """Whether evaluating `value` here produces a blob on this path.

    Two shapes, and they are the two the emitter already has a layout for:
    a container display (`_emit_list` lays out `[count][elements…]`) and a
    construction of an EMPTY container (`_emit_empty_blob`, the same eight bytes
    with a zero count) — with or without a `capacity=` reservation.  Everything
    else is False, which is the absent answer rather than a judgement: a name, an
    arithmetic expression, a container constructor with an operand that is not a
    reservation, a call to something this path does not place.  The last of
    those is `List[Int](n)`, which has to HOLD n elements and needs a
    reservation this compiler does not have at layout time — so it stays
    refused by name.  The decision is `blob_constructor_lowering` rather than a
    test spelled here, because the emitter asks the same question and the two
    answers have to be one.
    """
    if isinstance(value, (F.ListExpr, F.DictExpr, F.TupleExpr)):
        return True
    if not isinstance(value, F.CallExpr):
        return False
    callee = value.func
    base = callee
    while isinstance(base, F.SubscriptExpr):
        base = getattr(base, "obj", None)
    if not isinstance(base, F.IdentExpr):
        return False
    # `blob_constructor_lowering`, not a test spelled here: a kind claimed for a
    # slot has to come from the same rule the emitter applied, or
    # `ctor_establishes_slot` would open a door the emitter shuts. That is the
    # whole reason it is one function — it is what stopped
    # `std/collections/binary_heap.mojo`, whose SECOND `__init__` builds
    # `List[Self.T](capacity=capacity)` and whose first one builds
    # `List[Self.T]()`.
    return blob_constructor_lowering(
        base.name, getattr(value, "args", None),
        getattr(value, "kwargs", None)) is not None


def frame_slot_declared_annotation(candidates, name, decls=None) -> str | None:
    """The one annotation every candidate declares for `name`, or None.

    The same agree-or-refuse as `frame_slot_field_kind`, asked for the TEXT
    rather than the kind, because the text is what a refusal has to quote: a
    reader who is told "this slot holds a list but the value is not there" can
    only check that against the source if the message spells what the
    declaration said.  Two candidates that spell the same type two different
    ways (`List` and `list`) still agree on the base, so the base is what is
    compared and the first spelling is what is printed.

    "Declared" is the older half of what this now reads: `decls` brings the
    constructor spelling in, so the text may be a type `__init__` assigns rather
    than one the class body annotates — the same answer, from
    `struct_field_type`, with the same agreement rule over the same candidates.
    """
    cands = list(candidates or ())
    if not cands:
        return None
    rows = field_type_rows(cands, name, decls)
    bases = {base for _sn, base, _ann, _why, _ev in rows if base is not None}
    if len(bases) != 1 or any(base is None for _sn, base, _a, _w, _e in rows):
        return None
    return rows[0][2]


def frame_slot_field_is_dict(candidates, name, dict_names=(), decls=None):
    """Whether a FRAME SLOT's field is declared a DICT, agreed over candidates.

    The dict-ness TWIN of `frame_slot_field_kind`, and it is a separate function
    for the reason `global_slot_is_dict` is a separate function from
    `global_slot_kind`: on this path all four container annotations are ONE word
    — `List[Int]`, `Tuple[Int, Int]`, `Set[Int]` and `Dict[String, Int]` are a
    pointer to a blob with an 8-byte count header — so the kind answers "how wide
    is an element" and cannot answer "does a subscript with a string index mean
    a key lookup". Carrying it on the kind would make one of the two answers
    wrong.

    Same agree-or-refuse, same reader: `frame_slot_declared_annotation` over the
    candidates and `declared_type_is_dict` over the agreed annotation, so a
    holder two candidate structs disagree about is None rather than a pick.

    **What it deliberately does NOT carry is `struct_field_kind`'s VALUE gate,
    and the difference is a decision rather than an omission.** That gate exists
    because `len(self.xs)` on a field whose slot nothing established is a load
    from address 0 — and the gate's own docstring records that with the gate
    lifted the program BUILT on both architectures and died of SIGSEGV. The same
    hazard is real here, and the caller is what makes it decidable: a dict
    subscript is only a key scan when the INDEX is a string, and the emitter's
    dict dispatch asks that first — `dict_literal_key_value_kind`'s per-key gate,
    which answers only when the literal HOLDS the key and refuses otherwise; the
    four cases in `test_formal_value_model.py` around
    `a_dict_subscript_is_the_kind_of_the_pair_under_that_key` are it, including
    the field spelling a declared `Dict` field cannot reach. So the shape that
    is refused on the value axis is `len`, and the shape that is refused here is
    `d[0]` — an integer index against a field declared `Dict`, which is a blob
    element read and always was.

    A field with no DECLARED type, or one whose candidates disagree, is None:
    that is "this path cannot say", which every reader of a dict-ness boolean
    must keep as its own answer rather than reading as False."""
    ann = frame_slot_declared_annotation(candidates, name, decls)
    if ann is None:
        return None
    return declared_type_is_dict(ann, dict_names)


def frame_slot_field_is_bool(candidates, name, bool_names=(), decls=None):
    """Whether a FRAME SLOT's field is declared a `Bool`, over its candidates.

    `frame_slot_field_is_dict`'s twin on the BOOL axis, and it is the same
    function for the same reason that one is: a `Bool` field is `INT_KIND` (a
    word holding 0 or 1) and the KIND cannot carry the one thing about it that
    is observable — CPython prints `True`/`False` where `is_number_kind` says
    `%lld`. Same agree-or-refuse, same reader
    (`frame_slot_declared_annotation`), same None-for-"cannot say".

    `struct_field_kind`'s VALUE GATE is deliberately NOT carried here, and the
    reason is that this axis has no reader which can fault: the answer only ever
    changes what TEXT a `print` writes, and the worst a stale `True` in the slot
    can do is print `True` where the previous behaviour printed whatever the
    word held. `frame_slot_field_is_dict`'s own paragraph states why that is a
    decision there (a dict subscript IS a key scan, so a wrong answer reads
    memory) and why it is not one here.
    """
    ann = frame_slot_declared_annotation(candidates, name, decls)
    if ann is None:
        return None
    return annotation_is_bool(ann, bool_names)


def frame_slot_field_kind(candidates, name, int_names=(), string_names=(),
                          decls=None, dtype_names=(), float_names=()):
    """The kind a FRAME SLOT's field holds, agreed over the holder's candidates.

    The agree-or-refuse rule, applied to the question the kind tables ask, and
    built on D2's `struct_field_declared_type` / `field_type_rows` rather than a
    second walk of the candidates: every candidate must DECLARE the field, and
    every declaration must reduce to the same base name.  One candidate that
    does not declare it, or two that name different types, gives None — and
    None is the answer, not a fallback, because the two cases it is refusing
    are the two that would otherwise be a wrong number (see the note above).

    A single candidate is the common case and goes through the same rule rather
    than a shortcut, so `h.f` on a holder of known type and on a holder of
    doubtful type are decided by one function.

    The per-field `struct_field_kind` gate applies to every candidate: a kind
    here is a claim about the VALUE in the slot, not only about its type, and
    a candidate whose field has no materializable default does not support one.
    """
    cands = list(candidates or ())
    if not cands:
        return None
    ann = frame_slot_declared_annotation(cands, name, decls)
    if ann is None:
        return None
    kinds = {struct_field_kind(st, name, int_names, string_names, decls,
                              dtype_names, float_names)
             for st in cands}
    kinds.discard(None)
    return kinds.pop() if len(kinds) == 1 else None


def method_owner_struct(structs, fn_name):
    """The struct whose method compiles to `fn_name`, or None.

    A struct's methods are lifted to `<Struct>_<method>` (`_struct_methods` in
    formal/build.py), so the emitter that is emitting `R_size` needs to be able
    to say "this is a method of R" to type `self.<field>` — and a lifted name is
    the only record of the owner that reaches a backend, because the method's
    own `FunctionDef` carries no owner.

    Searched rather than derived from the name's prefix because a struct name
    may itself contain `_` (`_DictKeyIter`), so the split point is not a
    function of the spelling; the search is over this module's own methods, so
    it is a handful of string comparisons per emitted function and the answer
    is exact rather than a guess about where the name's prefix ends.
    """
    for st in (structs or {}).values() if isinstance(structs, dict) else (
            structs or ()):
        for m in struct_methods(st):
            if method_function_name(st.name, m.name) == fn_name:
                return st
    return None


def one_word_receiver_kind(struct_def, int_names=(), string_names=(),
                           decls=None, dtype_names=(), float_names=()):
    """The kind a ONE-WORD struct's receiver word holds, or None.

    The receiver of a struct with exactly one field IS that field — `self.<f>`
    is `self`, and the codegen rewrites the two to one name
    (`_rewrite_self_fields`) — so the receiver's kind is the field's declared
    kind, read by `struct_field_kind`.  This is the shape that makes
    `len(self)` on a one-field list-backed struct answerable, and it is the
    same fact `_one_word_field_map` in formal/build.py already relies on.

    `None` for a struct of more than one field, and that is not a shrug: its
    receiver is the ADDRESS of a frame of 8-byte slots, and no declared field
    type describes an address.  `len_refusal`'s frame row is the true message
    for that one, and it is reached by asking about the OPERAND's type rather
    than by this function.

    **The count check this used to open with is DEAD and was removed**, because
    the line under it subsumes it: `struct_sole_field_name` is
    `struct_field_names(st)[0] if len(...) == 1 else None`, so "not exactly one
    field" already answers `None` here and the two tests could only ever agree.
    What it cost was a SECOND whole-struct walk per ask — `struct_field_count`
    derives the field set by walking every method body of the struct twice, and
    so does `struct_sole_field_name`, so the guard doubled the price of the
    question it was guarding.  This is the same provably-dead filter
    the 2026-10-03 build-cost measurement's §4.1 (doc in git history) removed from
    `struct_derived_names`, and the reason it is worth writing down rather than
    leaving as an unexplained simplification: a reader who deletes the `None`
    test on the strength of "the count already said so" would be deleting the
    only thing that answers `struct_def is None`.
    """
    if struct_def is None:
        return None
    only = struct_sole_field_name(struct_def)
    if only is None:
        return None
    return struct_field_kind(struct_def, only, int_names, string_names,
                             decls, dtype_names, float_names)


def string_slice_refusal(base_kind, spelled_obj: str) -> str | None:
    """Why `obj[start:stop]` cannot be lowered when `obj` is a string, or None.

    A slice is a container operation: it reads a count, walks elements at a
    stride, and builds a NEW container. Every one of those steps is wrong for a
    `char *`, and the first one is the fatal one — the count is read from offset
    0 of the object, which for a `char *` is the first eight CHARACTERS, so the
    walk starts in the middle of the string with a length taken from its own
    first two letters. Measured on both backends: `s = "abcde"; printf("[%s]",
    s[1:])` died with SIGSEGV (exit 139) on arm64 and on x86-64.

    A crash, not a wrong answer, and that is worth saying plainly: a segfault is
    at least loud, and this is the mildest member of the family in
    bugs/formal/FORMAL_string_value_model.md. It is refused rather than lowered because
    the result would have to be a NEW container, and the one shape a slice of a
    string can have — an interior pointer `s + k` for a suffix, or the NUL-
    terminated bytes up to an end offset for a bounded one — is a string whose
    length is a NUL-truncated computation, so a bounded slice has no
    representation at all on this path (a slice of a string that contained a NUL
    would be silently truncated; see the cost list in that document). There is
    no buffer to build into either, which is the same missing buffer that makes
    `upper`/`replace` a refusal.

    The suffix case is the one that COULD be lowered (`s[1:]` is `s + 1`, an
    interior pointer this path already makes for `lstrip`), and it is still
    refused, because lowering half the family and not the other half is how two
    spellings of one question come to disagree — the `_emit_binop` /
    `_emit_branch_unless` lesson, twice over. If the suffix lowering lands it
    belongs here as a third row keyed on the bounds, not as a special case in a
    backend.
    """
    if not string_operand_is_string(base_kind):
        return None
    return (
        f"a slice of a string is refused. {spelled_obj} is a string, and a "
        f"string on this path is a bare `char *`, so a slice is a container "
        f"operation on it: the count would be read from offset 0 of the "
        f"pointer, which is the first eight CHARACTERS of the string rather "
        f"than a length. Measured on both backends, `s = \"abcde\"; "
        f"printf(\"[%s]\", s[1:])` died with SIGSEGV (exit 139). A suffix "
        f"slice is in fact just `s + k`, an interior pointer this path can "
        f"already make, so this is a missing lowering rather than a missing "
        f"capability — but a BOUNDED slice has no representation here at all, "
        f"so neither does. Index with an integer offset (`{spelled_obj}[i]`, "
        f"which yields the byte) or use a method; see "
        f"bugs/formal/FORMAL_string_value_model.md")




# ── `in` / `not in` on a string haystack ──────────────────────────────────
#
# The measured state of this, on the tree this was written on, on BOTH
# backends: `if "ell" in s:` where `s = "hello"` terminated the process with
# SIGBUS. Not a wrong answer — a crash — and the two architectures agreed on
# that much, which is the only good news in it. The cause is the same one as
# everywhere else in this section: the haystack is a `char *`, and the
# membership path had no string case for a haystack that is not a syntactic
# literal, so it read the first eight bytes of the CHARACTERS as a blob count
# and walked off the end of the mapping. x86-64 had no string case at all, so
# `"bc" in "abcd"` scanned the interned bytes as a blob; where that did not
# fault it returned FALSE, which is a wrong answer rather than a crash.
#
# So this is a libc call, on both backends, and the same libc call `find`
# already makes:
#
#     "ell" in s        ->   strstr(s, "ell") != NULL
#     101 in s          ->   strchr(s, 101)     != NULL
#
# The argument order of `strstr` is the whole method and it is the reason this
# is a table rather than a one-liner in a backend:
# `strstr("bc", "abcabcabc")` is a well-defined NULL, so getting it backwards
# does not crash, does not look wrong in the image, and returns FALSE for every
# haystack that contains its needle — which is every real use of `in`. It is
# `strstr(HAYSTACK, NEEDLE)`.
#
# `strchr` rather than a hand-written byte loop, for the reason `strspn` replaced
# the `lstrip` loop: it IS the algorithm, it cannot be half-right, and there is
# then nothing to keep in step between two architectures. `strchr` was checked
# to BIND on both backends before being relied on here (the x86-64 `strcmp`
# observation in bugs/formal/FORMAL_string_value_model.md is why that is worth a
# measurement rather than an assumption): with `STRING_COMPARE_SYMBOL` pointed
# at it, a program that calls it ran to completion and returned a non-NULL
# pointer on arm64 and on x86-64.
STRING_SEARCH_SYMBOL = "strstr"
STRING_BYTE_SEARCH_SYMBOL = "strchr"

# The two shapes `in`/`not in` takes when the haystack is a string. Which one
# is decided by the NEEDLE's kind, because that is what decides the libc call.
STRING_MEMBERSHIP_SUBSTRING = "strstr"   # needle is a char *  → strstr
STRING_MEMBERSHIP_BYTE = "strchr"        # needle is an int    → strchr


def string_membership_lowering(left_kind, right_kind) -> str | None:
    """How `needle in haystack` lowers when the haystack is a string, or None.

    None means "not a string membership" and the caller keeps whatever it did
    before, which for a list/tuple/dict haystack is the blob scan.

    The needle decides the call and nothing else does. A string needle is
    `strstr`; a byte needle is `strchr`. An unclassified needle (None kind) is
    NOT treated as a byte: `int in str` and `str in str` are different
    questions, and guessing which one was meant is how a membership test comes
    to answer the wrong one. An unclassified needle is left to the caller,
    which for a haystack that is a string means the blob scan — so this
    function returning None for it is deliberate, and the backends' own
    refusal for an unusable haystack is what the reader sees.

    THE BYTE CASE HAS AN EDGE, and it is the reason this is a table and not a
    two-line call. `strchr(s, 0)` returns a pointer to the terminating NUL, so
    it is non-NULL, so a plain `!= NULL` would make `0 in "abc"` TRUE. Python
    says FALSE, and on this representation it is certainly false: the only NUL
    in a string is the one that ends it. The backends therefore have to test the
    byte against zero before the call, and the test is one instruction in front
    of it on both.
    """
    if not string_operand_is_string(right_kind):
        return None
    if string_operand_is_string(left_kind):
        return STRING_MEMBERSHIP_SUBSTRING
    if left_kind == INT_KIND:
        return STRING_MEMBERSHIP_BYTE
    return None


def type_index_refusal(index_kind, spelled_index: str) -> str | None:
    """Why a TYPE cannot be a subscript index, or None when it is not one.

    The sibling of `string_index_refusal` one level up: that one declines a
    string index because `s + i` would add two addresses, and this one declines
    a TYPE index because a tag is not an offset at all. Asked at the same
    single choke point — `_emit_subscript_addr`, which a read, a store and an
    augmented assignment all pass through — so all three are covered by one
    call, and BEFORE the base's own shape is asked, because the base does not
    decide the answer: `xs[bool]` and `s[bool]` are the same mistake and the
    second one segfaults.

    It is not a reworded row of anything. Measured on this tree, both
    architectures, `xs = [10, 20, 30]; printf("%d", xs[bool])`:

        arm64   exit 1, nothing printed
        x86-64  exit 1, nothing printed

    A tag is a hash of a type's name — a large positive 63-bit number — so it
    bounds-checks against a three-element blob and takes the out-of-range exit.
    That is the bounds check doing its job on a number the source never wrote,
    which is why this is a REFUSAL and not a cheaper index: there is no
    reading of a type that is an element position.

    `index_kind` is the classifier's answer rather than the node, so this fires
    for a local bound to a type as well as for the bare name, which is the
    second half of the same defect: `t = bool; xs[t]` is the same program with
    one more line in it.
    """
    if index_kind != TYPE_KIND:
        return None
    return (
        f"`{spelled_index}` is a TYPE used as a subscript index, and on this "
        f"path a type is one 64-bit TAG — a hash of the type's name — so it is "
        f"a number, and there is no element position a type corresponds to. "
        f"Measured on both backends: `xs = [10, 20, 30]` with `xs[bool]` built, "
        f"ran and exited 1 with nothing printed, because the tag bounds-checks "
        f"against a three-element blob and takes the out-of-range exit — the "
        f"bounds check doing its job on a number the source never wrote. Index "
        f"with an integer, or compare the value with the type instead, which "
        f"is what a tag is for")


def unstated_base_string_index_refusal(base_is_dict: bool, base_kind,
                                       index_kind, spelled_base: str,
                                       spelled_index: str) -> str | None:
    """Why a string index against a base whose SHAPE nothing states is not
    lowered here, or None when it is.

    THE RESIDUE OF THE PAIR THE SOURCE DOES NOT CHOOSE BETWEEN, and it is the
    one thing in this section that turns a fault into a diagnostic. A string
    index means one of two entirely different things on this path — a dict KEY
    scan (`d["a"]`) or a byte offset into a `char *` (`s[0]`) — and which one it
    is depends on the base's shape, not on the index. When the base's shape is
    known, each case has its own path (`_is_dict_subscript` /
    `_is_string_subscript`) and both work. When NOTHING states it, the emitter
    falls back to "a blob", and the blob walk takes the key's interned ADDRESS
    as an ELEMENT OFFSET.

    Measured on this tree, both architectures, for the one spelling with no
    evidence at all — a parameter:

        def show(d) -> Int:
            printf("%d|", d["a"])
            return 0
        show({"a": 1})

        arm64   exit 1, nothing printed
        x86-64  exit 1, nothing printed

    The same program with `d: Dict[String, Int]` annotated answers `1|` on both,
    because the annotation is the evidence; and `d = mk()` with a dict-returning
    `mk` answers it too, because the callee is. What is left is the base no
    source statement and no declaration describes — and a refusal is the honest
    answer there, because the two readings are not variations on one answer:
    one is a scan over pair slots and the other is `base + i`.

    NOT refused, deliberately, because each of these is a real reading and
    lowering it is right:

      * a string base with an integer index (`s[0]`), a byte read;
      * a string base with a string index — `string_index_refusal` owns that
        one, and the message here would be a second spelling of one refusal;
      * a base known to be a dict, whatever produced the key;
      * an INTEGER index against a base of unstated shape, which is a blob
        element read and has always been the default.

    So the pair this refuses is exactly (index is a string, base is neither a
    string nor a dict), which is the same narrowness the emitter's own dispatch
    needs and not one case wider.
    """
    if base_is_dict or string_operand_is_string(base_kind):
        return None
    if not string_operand_is_string(index_kind):
        return None
    return (
        f"`{spelled_base}[{spelled_index}]` cannot be lowered: the INDEX is a "
        f"string and nothing in the source says what `{spelled_base}` holds. "
        f"On this path a string index is either a dict KEY scan — `d[\"a\"]`, "
        f"the value under the key — or a byte offset into a `char *` "
        f"(`s[0]`), and which one it is comes from the BASE, which here is "
        f"unstated. Measured on both backends: an unannotated parameter with a "
        f"string subscript built, ran and exited 1 with nothing printed, "
        f"because the fallback read the key's address as an element offset and "
        f"the bounds check failed on it. Annotate the parameter, bind the "
        f"container to a name, or read the value another way")


def string_position_verdict(construct: str, haystack, needle, hay_text=None):
    """`(verdict, why)` for a construct whose answer is a POSITION in a string.

    The sibling of `string_codepoint_verdict`, and the reason it is a separate
    function is that a position has TWO operands where a length has one — the
    text searched and the text searched for — and only one of them has to be
    known.

    `STRING_POSITION_STRLEN` — the offset a `strstr` returns is a character
    offset; emit the call as before. `STRING_POSITION_FOLD` — `why` is the
    INTEGER Python's `str.find` returns for this pair, and neither machine
    instruction nor libc call is involved. `(None, message)` — refuse.

    **Why a known-ASCII HAYSTACK alone is enough**, and this is the whole reason
    the needle's text is not needed in the permissive row: UTF-8 is
    self-synchronising, so a byte substring of two well-formed UTF-8 strings
    can only begin at a character boundary, and a Python `str` always begins
    with either an ASCII byte or a lead byte — so a non-ASCII needle cannot
    match anywhere inside ASCII text at all. `strstr`'s offset over ASCII text
    is therefore a character offset whatever the needle holds.
    """
    hay = string_literal_text(haystack) if hay_text is None else hay_text
    if hay is not None and text_is_ascii(hay):
        return STRING_POSITION_STRLEN, None
    if hay is not None and string_literal_text(needle) is not None:
        return STRING_POSITION_FOLD, str(
            hay.find(string_literal_text(needle)))
    if non_ascii_strings():
        return None, codepoint_refusal(construct, spelled(haystack))
    return STRING_POSITION_STRLEN, None


def receiver_is_declared_bytes(fn, base, decls=None, functions=None) -> bool:
    """True when this image declares `base`'s pointee to be ONE byte — `bytes`.

    **A `bytes` and a `str` are different answers, not different types.** CPython
    says `"héllo"[1]` is one character and `b"héllo"[1]` is the integer 195, so
    "read one byte at `base + index`" is CPython's own answer for the second and
    a wrong one for the first. That is what makes a one-byte pointee a
    *criterion* rather than a shortcut: it is the spelling that says which of
    the two objects this path is holding, and the criterion is checked only
    where the two answers differ (see `string_element_refusal`).

    **`pointer_pointee` is the reader, not a second one.** It is the reader the
    emitter already asks for the width of the very same load — `base + i*width`
    with `width` from `pointer_pointee` — so a byte exemption and a byte width
    cannot come apart: if this says `bytes`, the load the emitter emits is the
    one-byte load, and if `pointer_pointee` cannot establish a pointee this
    returns False and the refusal stands.

    **`fn is None` is False**, which is the conservative direction and the reason
    the callers that have no function in hand (`test_formal_unicode.py`'s
    in-process rows) get the refusal rather than an exemption nobody measured.

    The pointee spellings are read through `annotation_base_name`'s inner
    argument so `Pointer[UInt8]`, `UnsafePointer[UInt8]` and `DTypePointer[
    UInt8]` are one answer; `Int8` is here beside `UInt8` because a signed byte
    buffer is the same one-byte access and the sign is the width question the
    emitter's own `subscript_base_lowering` already decided.
    """
    if fn is None or base is None:
        return False
    pointee, _why = pointer_pointee(fn, base, decls or {}, functions)
    return pointee in BYTE_POINTER_ELEMENTS


# The pointee spellings that make a pointer a BYTE buffer. A set rather than one
# name because `pointer_pointee` reports the pointee's BASE name — the reduction
# `annotation_base_name` does on the type argument — and every pointer spelling
# in `POINTER_TYPE_CTORS` reduces to its own element type, so the element is the
# one thing to compare and there is one answer for all of them.
BYTE_POINTER_ELEMENTS = frozenset({"UInt8", "Int8"})


def string_element_refusal(base, index, fn=None, decls=None,
                           functions=None) -> str | None:
    """Why `base[index]` is not a CHARACTER of `base`, or None when it is.

    A string element on this path is one BYTE at `base + index`, and CPython's
    `s[i]` is a one-CHARACTER `str`. Those agree about WHICH BYTE to read and
    disagree about everything else: for ASCII the byte is the character, and for
    anything else `base + index` walks into the middle of a multi-byte sequence
    and reads a continuation byte that is not a character at all.

    ## `bytes` is not `str`, and the receiver's DECLARED type is what says so

    **`fn`/`decls`/`functions` are the receiver's declarations, and they are the
    difference between a `str` and a `bytes`.** CPython agrees with this
    function's refusal about `str` and disagrees with it about `bytes`, because
    CPython's two objects differ in the answer rather than only in the type:
    `"héllo"[1]` is a character and `b"héllo"[1]` is the integer 195. So a
    receiver the source declares `Pointer[UInt8]` is a byte buffer, its subscript
    is a byte load, and the byte is the answer — there is no character for this
    refusal to protect.

    Without those three arguments this is the refusal about a receiver whose
    type NOTHING states, which is why the default is to refuse and the
    exemption needs the declarations: `formal/arm64_codegen.py` and its x86-64
    twin are the two callers that have them, and `test_formal_unicode.py` pins
    the `fn=None` answer as the conservative one.

    **The two spellings of the same declaration used to get opposite answers,
    which is the whole measurement.** With one non-ASCII literal in the image,
    one em-dash in a docstring, on both architectures, exit 0:

        fn take(e: Pointer[UInt8]): return e[3]     ->  BUILT (a byte load)

        fn str_alloc(n) -> str: return malloc(n+1)
        def get(e):
            var d: Pointer[UInt8] = str_alloc(8)   ->  REFUSED, this message
            d[0] = e[0]
            return d[0]

    Same declared type, same byte subscript, and the parameter reading was the
    byte one because `ValueKinds` seeds an annotated `Pointer[UInt8]` PARAMETER
    to `INT_KIND` while `_value_kind` reads the LOCAL off its initializer's
    declared return (`str_alloc` declares `-> str`), which is `STR_KIND`. So
    `formal/hostmods/os/_syscalls.mojo`'s `fs_dirent_name` — which copies a
    `readdir(3)` name one byte at a time, and whose own docstrings call the
    annotation load-bearing for exactly that — was refused by a rule that asks
    about characters, and 31 non-ASCII em-dashes in that file's prose were
    enough to do it. That took `os`, `shlex`, `posixpath`, `argparse` and
    `time` down with it: each imports `os._syscalls`, so each image carries
    those literals.

    **What it costs, measured over the 743 `.mojo` files of this repository and
    its stdlib** (every parseable file; `pointer_pointee` is the reader, which
    is the same one the emitter's own `subscript_base_lowering` asks for the
    width, so the exemption and the width cannot come apart):

        22 subscripts whose receiver's declared pointee is one byte,
        22 of them in ONE file — formal/hostmods/os/_syscalls.mojo —
        and every one is a byte copy or a byte read of a `struct dirent`,
        a `le16`/`le32`/`le64` decoder, or a `name[0] == 46` test.

    Of those 22, twenty already took the byte path (a `Pointer[UInt8]`
    parameter is not `STR_KIND`) and two — `d[i]` — were refused. So the
    exemption makes twenty-two sites agree instead of adding a reading: it does
    not introduce a byte answer anywhere that did not already have one.

    ## The residual, stated rather than hidden

    A `Pointer[UInt8]` that holds TEXT and is subscripted as a CHARACTER read
    would now get the byte where it got a refusal. This tree has no such site
    (the census above), and the host module that declares most of them says out
    loud why it does not use the byte subscript to ask a character question:
    `formal/hostmods/os/_syscalls.mojo`'s `str_at` is
    "A character test with no byte load, which is the only way to ask this
    question on this target". So the byte subscript is not this path's way of
    reading a character, in this module or in this corpus; what a `str` element
    read costs is still recorded in `bugs/formal/FORMAL_string_value_model.md` and is
    still refused everywhere else.

    **This is a REFUSAL and not a fold, and the difference from `len` is the
    answer itself.** The character count is a NUMBER and a literal's text gives
    it here; a one-character string is a NEW OBJECT, and a string value on this
    path is a bare `char *` to bytes in the image's text section — which is
    mapped read+execute and is interned by content, so there is nowhere to put
    the two bytes of an `é` and no way to intern a one-character string per
    character position. That is `LENGTH_DEPENDENT_METHODS`'s missing buffer,
    reached from an index instead of from `upper()`.

    Measured on both architectures, `s = "日本"; printf("[%c]", s[1])` printed a
    single `0x9c` — the second byte of `本` (`E6 9C AC`) — which is not a
    character, is not printable, and makes the program's own output invalid
    UTF-8. `s = "héllo"; s[1]` printed `0xc3` for the same reason.

    An index a KNOWN TEXT makes answerable is still not answerable, because the
    obstacle is where the answer would live rather than what it is: so this
    fires for a non-ASCII LITERAL receiver exactly as it does for a name. The
    two things that do clear it are the condition on the whole image, which is
    the TEXT ENCODING block's argument (no literal with a byte >= 0x80 anywhere
    means no string in the image can have one, so every element read is a
    character), and a receiver the source declares a byte buffer — see the
    section above.
    """
    if not non_ascii_strings():
        return None
    # The BYTE exemption is asked AFTER the image test and not before it,
    # because it is the one reader here that walks the function's declarations
    # and its call sites, and an all-ASCII image must not pay for it. The
    # order is also the safe one for the same reason the image test is first:
    # a false refusal is the expensive direction here, not the cheap one.
    if receiver_is_declared_bytes(fn, base, decls, functions):
        return None
    text = string_literal_text(base)
    known = (f" The receiver is the literal {text!r}, so this build does know "
             f"which bytes it has — and that is the problem rather than the "
             f"cure: the answer Python wants is a one-CHARACTER `str`, which is "
             f"a new object, and this representation has nowhere to put one."
             if text else
             f" This build cannot see what text the receiver holds, and neither "
             f"could it place the answer: see the sentence on the missing "
             f"buffer.")
    return (
        f"{spelled(base)}[{spelled(index)}] is refused on a string whose text "
        f"is not ASCII. A string here is a bare `char *` to BYTES, so the "
        f"subscript is `base + index` and what it reads is one byte — while "
        f"CPython's `s[i]` is one CHARACTER. For ASCII those are the same byte; "
        f"for a multi-byte character they are not, and `base + index` lands in "
        f"the middle of the sequence: measured on both architectures, "
        f"`s = \"日本\"; printf(\"[%c]\", s[1])` printed a single `0x9c` — the "
        f"second byte of `本` — which is not a character and is not even valid "
        f"UTF-8 on its own. This image holds a string literal that is not ASCII, "
        f"so some string in it can have a character `base + 1` walks into.{known} "
        f"Refused rather than emitting the byte, because a byte where a "
        f"character belongs is a wrong value AND a wrong one that reads "
        f"plausible: for `s = \"héllo\"`, `s[0]` is 104 and `s[2]` is 108, "
        f"which is `l`, and the wrong answers are the right answers for the "
        f"NEIGHBOURING indices. What this path CAN do: keep the text ASCII, "
        f"which is what every other answer here assumes; or read the byte "
        f"deliberately, with a `Pointer[UInt8]` subscript and the arithmetic "
        f"written out, which is what a program that wants bytes wants")


def string_index_refusal(base_kind, index_kind,
                          spelled_index: str) -> str | None:
    """Why `s[i]` cannot be lowered when `i` is itself a string, or None.

    The same class as everything else in this section, one level down: the
    subscript on a string is `s + i` on a bare `char *`, so a string INDEX
    makes it integer addition of two addresses. Measured on the tree this was
    written on, on BOTH backends, for `s = "abc"; t = "bc"; printf("%d", s[t])`:

        arm64   67          0x43 — the low byte of a text-section address
        x86-64  SIGSEGV     the sum of two addresses, dereferenced

    An address's low byte is the worst of the fabricated numbers in this file
    because it is small, printable and plausible: 67 reads like a character
    code, and a reader checking the output would have no reason to doubt it.

    NOT the same refusal as `string_operand_is_string(base_kind)` being false:
    this is about the INDEX. A string base with an integer index is `s + i`,
    which is real C pointer arithmetic and is lowered, giving the byte at that
    offset — see the `s[0]` case in bugs/formal/FORMAL_string_value_model.md for why
    that byte rather than a one-character String is a recorded divergence
    rather than a refusal.
    """
    if not (string_operand_is_string(base_kind)
            and string_operand_is_string(index_kind)):
        return None
    return (
        f"`{spelled_index}` cannot index a string on this path: a string here "
        f"is a bare `char *`, so the subscript is `s + i` — integer addition of "
        f"two addresses when the index is a string too. Measured on both "
        f"backends: `printf(\"%d\", s[t])` printed 67 on arm64 (the low byte of "
        f"a text-section address) and segfaulted on x86-64. Use "
        f"`s.find({spelled_index})`, which is lowered as a `strstr`, or index "
        f"with an integer offset, which is the pointer arithmetic this path "
        f"does have")




def del_refusal(target, base_is_string: bool = False,
                base_is_pointer: bool = False) -> str | None:
    """Why this `del` target cannot be lowered here, or None when it can.

    THE SHAPE-ASKED REFUSAL FOR `del`, and the one that closes a silent no-op
    rather than a fault.
    `FORMAL_del_of_a_subscript_is_a_silent_no_op_on_arm64` measured it
    on both architectures:

        del lst[0]      arm64  exit 0, `3 10` — the list still has 3 elements
        del lst[1:3]    arm64  exit 0, `4 10 20` — the slice is still there
        del d["a"]      arm64  exit 0, `2 2` — the key is still there
        del p[0]        arm64  exit 0, `9 20` — a POINTER, corrupted
        all five         x86-64 refused the STATEMENT (`DelStmt` was not in the
                         statement dispatch at all), so for `del` the two
                         architectures disagreed about whether the program had
                         an answer

    The arm64 cause was one `continue`: the `SubscriptExpr` branch sat below
    the `SliceExpr` branch's `continue`, so every subscript target fell off the
    end of the loop body and emitted NO instructions — which is why the build
    was green, the image ran, and nothing was removed. That is the one outcome
    this backend may not produce, and it is why the four `del` lowering helpers
    were dead code with no other caller: written, reviewed, and stranded behind
    a line nobody read twice. Three of them were also wrong once reached, which
    is what "dead code is not reviewed by running it" costs — the emitters'
    own comment about the branch polarity is in `arm64_codegen.py`'s
    `_emit_del_list_range`.

    So `del` is asked HERE, once, in a vocabulary both backends lower:

        name / member   a bare name or field — a no-op, and a documented one:
                        there is no GC and an SRA slot has no storage to free
        list_index      `del lst[i]` — shift left, count--
        slice           `del lst[a:b]` — memmove the tail, count -= b-a
        dict_key        `del d[k]` — shift-delete over the pair array
        string_index    REFUSED — see below
        pointer_base    REFUSED — see below
        stepped_slice   REFUSED — see below
        unnamed_base    REFUSED — see below
        unsupported     REFUSED — anything else

    The four refusals are the residue after the lowered shapes, and each one is
    TRUE OF THE SHAPE on this path rather than a statement that the construct is
    too new:

    * `string_index` — a string here is a bare `char *` into static storage, so
      `del s[0]` has no element to remove, no count to shift and nothing whose
      address this path could hand a caller. The byte it would have "removed"
      is a constant in `__TEXT`. Same question `string_index_refusal` asks of
      the other end of the subscript, and it is refused here for the same
      reason rather than lowered as a pointer decrement.
    * `pointer_base` — a `Pointer[T]` has no count header and no length, so
      there is nothing to shift the survivors into and nothing whose count to
      decrement: `del p[0]` on a `malloc`'d buffer whose first word is `10`
      printed `9 20`, because the first word was read as the COUNT and
      decremented while the buffer's contents stayed put. A buffer is not a
      list that forgot its length; it is a pointer, and the storage behind it
      belongs to something else.
    * `stepped_slice` — `del lst[0:4:2]` removes elements 0 and 2, and a
      shift-left is not that; it is a compaction with holes. Emitting the
      contiguous lowering would produce a list whose length is right and whose
      contents are wrong, which is the same silent wrong answer as the no-op.
    * `unnamed_base` — a base this path has no slot for: a call result, an
      attribute chain rooted at one, a temporary. `del mk()[0]` says "remove an
      element of a value that has nowhere to live", so the lowering would have
      to invent the storage first.

    `base_is_string` and `base_is_pointer` are the backend's own answers to
    "what does this base hold" — `_is_string_subscript` and
    `subscript_base_lowering`, the same two the READ path asks through
    `_emit_subscript_addr`, so a base this function accepts is a base the read
    path already lowers. The shape decides the refusal and the value decides
    WHICH refusal.
    """
    if isinstance(target, (F.IdentExpr, F.MemberExpr)):
        return None
    if isinstance(target, F.SliceExpr):
        if target.step is not None:
            return _del_shape_refusal(
                target, "stepped_slice",
                "a `step` removes elements that are not adjacent "
                "(`del lst[0:4:2]` removes elements 0 and 2), so the "
                "contiguous shift-left this path would emit produces a list "
                "of the right length and the wrong contents. There is no "
                "sound lowering of it here, and a wrong list is worse than "
                "no answer")
        return None
    if not isinstance(target, F.SubscriptExpr):
        return _del_shape_refusal(
            target, "unsupported",
            f"it is a `{type(target).__name__}`, and `del` on this path "
            "lowers a subscript target (a list index, a list slice or a dict "
            "key) and treats a bare name or field as the no-op it is")
    if base_is_pointer:
        return _del_shape_refusal(
            target, "pointer_base",
            "the base is a POINTER, and a pointer here has no count header and "
            "no length: there is nothing to shift the survivors into and "
            "nothing whose count to come down, so the lowering this path would "
            "emit decrements the first word of the buffer itself — measured on "
            "both architectures, `del p[0]` on a `malloc`'d buffer holding 10 "
            "printed 9. A buffer is not a list that forgot its length; use a "
            "slice assignment, or clear the element yourself")
    if base_is_string:
        return _del_shape_refusal(
            target, "string_index",
            "the base is a string, and a string here is a bare `char *` into "
            "static storage: there is no element to remove, no count to "
            "shift and nothing whose address this path could hand a caller — "
            "the byte would be a constant in `__TEXT`. A string is immutable "
            "here, so `del s[0]` has nothing to do")
    if getattr(target.index, "step", None) is not None:
        return _del_shape_refusal(
            target, "stepped_slice",
            "a `step` removes elements that are not adjacent "
            "(`del lst[0:4:2]` removes elements 0 and 2), so the contiguous "
            "shift-left this path would emit produces a list of the right "
            "length and the wrong contents. There is no sound lowering of it "
            "here, and a wrong list is worse than no answer")
    if not isinstance(getattr(target, "obj", None), (F.IdentExpr, F.MemberExpr)):
        return _del_shape_refusal(
            target, "unnamed_base",
            "the base is not a name or a field this path has a slot for, and "
            "`del` needs one: removing an element means writing a new count "
            "into the blob the base names, so a value with nowhere to live "
            "has nothing to write to. Bind the container to a name first")
    return None


def _del_shape_refusal(target, shape: str, why: str) -> str:
    """The `del` refusal text for `shape`, quoted from the source spelling."""
    return (f"`del {spelled(target)}` is not lowered on the formal path: "
            f"{why}.")


def string_has_static_storage() -> bool:
    """True when a string value's BYTES outlive the function that made it.

    Always True, and it is a function rather than a constant so that the
    question has a name at the place the answer is needed. The reasoning is in
    the section comment above: every string on this path is a literal interned
    into `__TEXT,__text` or an interior pointer into one, so its storage
    duration is static.

    WHY IT IS HERE, and who it is for: the frame-lifetime analysis in
    `formal/build.py` refuses a value that is the address of a frame when that
    value is returned, stored in a container, or handed to a callee whose
    meaning this path cannot see — and it reaches that rule for `String` and
    `StringSlice`, because the stdlib declares them as multi-field structs
    (three slots each) and wave 3's by-reference receiver makes a local bound
    from their constructor a frame address. 16 files in the stdlib sweep are
    refused by exactly that rule, and the message it prints — "the receiver of
    a multi-field struct is the ADDRESS of a frame of 8-byte slots that
    belongs to the function which created it" — is a FALSE STATEMENT about a
    value whose bytes are in the image's read-only text section and are still
    there after every function has returned.

    So: the rule is sound for a struct whose fields live in a frame, and
    unsound as applied to a `char *` to static bytes. The position half of
    that analysis (which argument positions a callee can be trusted with) is
    not this module's; this predicate is the string half of the answer, stated
    where both sides can read it. A reproducer, on both backends:

        struct String:                      # three fields, as the stdlib has it
            var _ptr_or_data: Pointer[UInt8]
            var _len_or_data: Int
            var _capacity_or_data: Int
        def make():
            s = String()
            s._len_or_data = 5
            return s                        # REFUSED: "a String receiver is
        def main(n):                        # returned from the function that
            return make().size()            # created it"

        def make():                         # the same program with the string
            s = "  hi".lstrip()             # kept as a char *:
            return s                        # BUILTS, and prints [hi]
        def main(n):
            printf("[%s]\\n", make())
    """
    return True


def string_method_result_kind(method: str):
    """The kind a lowered or folded string method yields, or None.

    Both tables, and the reason they are read together is a measured wrong
    answer rather than a tidy-up. `POINTER_BOUNDED_METHODS` records what the
    five libc-backed methods yield; `STRING_FOLDED_METHODS` records what the
    thirty-five folded ones yield. They have to agree about the RESULT rather
    than each knowing its own half, because the consumer is a classifier and a
    classifier that is told a `str` method yields a number reads a `char *` as
    an integer: `m = "ab".upper()` followed by `printf("[%s]", m)` printed an
    address, and `m == "AB"` compared a pointer against an integer. That is the
    `_expr_str_kind` lesson one level up, and the fold is the third way to reach
    the same place — a method whose result is misclassified poisons every use
    site after it, with a wrong answer rather than a diagnostic as the symptom.
    """
    entry = POINTER_BOUNDED_METHODS.get(method)
    if entry is not None:
        return entry[1]
    folded = STRING_FOLDED_METHODS.get(method)
    return folded[2] if folded is not None else None


def string_method_yields_string(call, receiver_is_str: bool) -> bool:
    """True when `call` is a lowered string method that produces a STRING.

    `receiver_is_str` is the caller's own answer to "is the receiver a char *",
    because each classifier has a different one to give: ValueKinds asks its
    own whole-function map, while a backend also has the flow-sensitive
    `_string_vars` and that one is better informed. The DECISION of what such a
    call yields belongs here so the two cannot drift — a method that one
    classifier calls a string and the other calls a word produces a program
    that is right up to the first `==` and wrong after it.

    `lstrip` is the only method this is true of today, and it is enough to
    matter: `m = s.lstrip()` followed by `m == "x"` is two statements, and
    without this the second one compares a pointer to an integer."""
    if not receiver_is_str:
        return False
    func = getattr(call, "func", None)
    if not isinstance(func, F.MemberExpr):
        return False
    return string_method_result_kind(func.member) == STR_KIND


def pointer_bounded_method(method: str):
    """The lowering name of a pointer-bounded string method, or None."""
    entry = POINTER_BOUNDED_METHODS.get(method)
    return entry[0] if entry else None
