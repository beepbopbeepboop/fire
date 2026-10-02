#!/usr/bin/env python3
"""test_formal_read_before_store.py — the DOMINANCE half of the check, against CPython.

`formal/model.py`'s `read_before_store` used to be an ordered walk with a
running `stored` set, so a branch arm's stores became visible to the code after
the branch. That made the check exact on straight-line code and silent on
everything else, and the shape it could not see is ordinary:

    def f(n):
        if n:
            p = 1
        printf("p=%d", p)

CPython raises `UnboundLocalError` whenever `n` is falsey; the formal backends
built it and printed whatever the CALLER left in the register, a word that
changed with the build and differed between the two architectures. It is now a
"definitely stored" fixpoint over the function's CFG: a store dominates a read
only when every path from the entry to the read passes one.

**Why this file is a unit test and not more rows in `test_formal_run.py`.**
Those rows build and RUN an image, which is the only way to check the end-to-end
behaviour, and they are the right place for the two refusals and the controls
that matter most. But the analysis itself has dozens of shapes, they are decided
before any code is emitted, and the interesting ones are the ones a "count the
arms" heuristic gets wrong — `try`/`except`/`else`/`finally` with a `return` in
the `finally`, a `break` out of one arm of a loop, a `match` with a wildcard arm,
a `del` on one path. Each of those as a build-and-run row is a compiler
invocation; as a call into `read_before_store` it is microseconds, so all of
them are here and the whole file costs no builds at all.

**THE ORACLE IS CPython, per probe value, and it is checked in both
directions** — which is the part that makes it more than a table of expected
answers:

  * the analysis refuses ⟹ CPython raised `UnboundLocalError`/`NameError` for at
    least one of the probe values. This is the soundness direction: a refusal
    the language would not have made breaks a program that runs, so the sweep
    has to be able to catch a rule that fires too eagerly.
  * the analysis does NOT refuse ⟹ CPython raised for NONE of the probe values.
    This is the direction that catches the analysis getting WORSE, which is the
    risk a fix like this carries: it is a stronger check than the walk it
    replaced, so its failure mode is refusing legal code.

The sweep is not a proof — five probe values cannot stand in for all of them, so
a case that raises only for `n == 7` would read as "ok" here. That is why every
case also carries an explicit `expect`, which pins the intended answer and is
what would catch a future change that quietly weakens the analysis. The sweep is
what would catch a change that quietly over-refuses.

    python3 test_formal_read_before_store.py [-v]
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fire_compiler as F            # noqa: E402
import formal.model as M             # noqa: E402
from formal.build import parse_module  # noqa: E402

# Values the probe is called with. `0` and `1` are the two that matter for a
# condition, `2` and `3` reach a second arm of a `match` or a comparison, and
# `10` is the startup stub's own `-n` default, so a case written against the
# formal entry point sees the value it would really see.
PROBE_VALUES = (0, 1, 2, 3, 10)

# (name, function body, expect)
#
# `expect` is "refuse" or "ok". Both are asserted against the analysis, and
# both are cross-checked against CPython run with each of PROBE_VALUES.
CASES = [
    # ── straight line: the part the old walk already decided exactly ──────
    ("stored_first_ok",
     "    q = 1\n    return q\n", "ok"),
    ("read_before_write_refused",
     "    return q + 1\n    q = 1\n", "refuse"),
    # `x = x + 1` is the canonical instance: the VALUE is read before the
    # target is written, and reading it after would make it look initialised.
    ("self_reference_refused",
     "    q = q + 1\n    return q\n", "refuse"),
    ("augmented_refused",
     "    q += 1\n    return q\n", "refuse"),
    ("parameter_is_stored",
     "    return n + 1\n", "ok"),

    # ── the shape the walk could not see: a store in only SOME arm ────────
    ("if_only_arm_refused",
     "    if n:\n        p = 1\n    return p\n", "refuse"),
    ("if_else_both_arms_ok",
     "    if n:\n        p = 1\n    else:\n        p = 2\n"
     "    return p\n", "ok"),
    ("if_elif_else_all_arms_ok",
     "    if n > 5:\n        p = 1\n    elif n > 2:\n        p = 2\n"
     "    else:\n        p = 3\n    return p\n", "ok"),
    # An `elif` chain with no `else`: the false edge falls through from the
    # LAST arm, and that arm's own condition can be false too, so the store in
    # it reaches no path. CPython raises at n == 0.
    ("if_elif_no_else_last_arm_refused",
     "    if n > 5:\n        p = 1\n    elif n:\n        p = 2\n"
     "    return p\n", "refuse"),
    # A SECOND `if` with no `else` does not undo the first one's arms: the
    # false edge reaches `return p` with whatever the `if`/`else` stored, so
    # `p` still dominates. The join is an intersection over PATHS, not a count
    # of stores, and this is the shape a too-eager rule refuses.
    ("second_if_does_not_undo_the_first_ok",
     "    if n:\n        p = 1\n    else:\n        p = 0\n"
     "    if n:\n        p = 2\n    return p\n", "ok"),

    # ── loops: the target is a definition in the HEADER, not the body ─────
    ("for_target_stays_bound",
     "    for i in range(3):\n        if i > 1:\n            break\n"
     "    return i\n", "ok"),
    # THE RECORDED DIVERGENCE, and the reason a `for` target is a definition
    # in the loop's header rather than something the body stores: CPython
    # leaves it unbound for an EMPTY iterable, so this raises there and the
    # analysis does not. Refusing the legal shape to catch the illegal one
    # would break `for i in range(0, 100): if i > 3: break` then `return i`
    # (returns 4) — `test_formal_run.py`'s `for_range_break`, and the shape
    # real code is written in. A register the caller left something in is a
    # better answer for a program that ran than a refusal is.
    ("empty_range_target_stays_bound",
     "    for i in range(0):\n        pass\n    return i\n", "ok",
     "CPython leaves a `for` target unbound for an empty iterable"),
    # The shape the old walk could not see at all: a store in a loop body,
    # read after the loop. `range(n)` may be empty, so the store does not
    # dominate — and CPython raises at n == 0, so this one is not a
    # conservatism question at all.
    ("store_in_loop_body_refused",
     "    for i in range(n):\n        t = i\n    return t\n", "refuse"),
    ("store_before_loop_ok",
     "    t = 0\n    for i in range(3):\n        t = t + i\n"
     "    return t\n", "ok"),
    # A statically NON-EMPTY iterable, so the body provably ran and the store
    # in it dominates. Without `_loop_body_always_runs` this would be refused,
    # which is a false refusal of `for i in range(3): total = i` followed by
    # reading `total` — ordinary code.
    ("nonempty_literal_range_body_store_ok",
     "    for i in range(3):\n        t = i\n    return t\n", "ok"),
    ("nonempty_literal_list_body_store_ok",
     "    for i in [1, 2, 3]:\n        t = i\n    return t\n", "ok"),
    ("empty_literal_list_body_store_refused",
     "    for i in []:\n        t = i\n    return t\n", "refuse"),
    ("empty_range_body_store_refused",
     "    for i in range(0, 5, -1):\n        t = i\n    return t\n", "refuse"),
    # THE OTHER LIMIT THAT CAN REFUSE A PROGRAM THAT WORKS, and it is pinned
    # rather than hidden: the body's first iteration depends on the condition
    # being true on ENTRY, which for `i < 3` with `i = 0` is a constant-
    # propagation question the CFG does not ask. CPython runs this; the
    # analysis refuses it. `while True:` and a `while` over literal bounds —
    # the shapes where the answer is decidable — are NOT refused, which is
    # what `_loop_body_always_runs` is for.
    ("while_body_store_refused",
     "    i = 0\n    while i < 3:\n        t = 1\n        i = i + 1\n"
     "    return t\n", "refuse",
     "the condition is not decidable on entry, so the body's first iteration "
     "is not known to happen"),
    ("while_true_body_store_ok",
     "    while True:\n        t = 1\n        break\n    return t\n", "ok"),
    ("while_literal_true_body_store_ok",
     "    while 1 < 2:\n        t = 1\n        break\n    return t\n",
     "ok"),
    ("while_literal_false_body_store_refused",
     "    while 2 < 1:\n        t = 1\n    return t\n", "refuse"),
    ("while_condition_read_is_a_read",
     "    i = 0\n    while i < 3:\n        i = i + 1\n"
     "    return i\n", "ok"),
    # A `break` out of ONE arm: the path that falls out of the loop with the
    # condition false reaches the join without the store, and CPython raises
    # there. The row below it is what makes both paths store.
    ("break_in_one_arm_refused",
     "    for i in range(3):\n        if n:\n            p = 1\n"
     "            break\n    return p\n", "refuse"),
    ("break_and_else_arm_both_store_ok",
     "    for i in range(3):\n        if n:\n            p = 1\n"
     "            break\n        else:\n            p = 2\n"
     "    return p\n", "ok"),
    # A `continue` is a jump to the NEXT iteration, not an exit, so it is not a
    # path to the join — and the store beside it still does not dominate.
    ("continue_is_not_an_exit",
     "    for i in range(3):\n        if n:\n            continue\n"
     "        p = 1\n    return p\n", "refuse"),
    # The loop's `else` clause runs when the loop finished without a `break`,
    # INCLUDING when the iterable was empty, so an empty `range(0)` still
    # reaches it — and a store in the BODY is then on no path at all.
    ("loop_else_is_reached_by_an_empty_loop",
     "    for i in range(0):\n        p = 1\n    else:\n        pass\n"
     "    return p\n", "refuse"),
    # Nested loops: the inner header's `for` target is defined for the outer
    # body, and the outer target for everything after both.
    ("nested_loop_targets_ok",
     "    for i in range(3):\n        for j in range(3):\n"
     "            if j:\n                break\n    return i + j\n", "ok"),
    ("inner_target_read_after_outer_refused",
     "    for i in range(n):\n        for j in range(3):\n            pass\n"
     "    return j\n", "refuse"),

    # ── `try`: the arms are a SET, and `finally` is reached from all of them ──
    ("every_handler_stores_ok",
     "    try:\n        p = 1\n    except ValueError:\n        p = 2\n"
     "    return p\n", "ok"),
    # A handler that stores nothing is a path to the join that stores nothing,
    # and nothing in the graph says the handler will not run — so this refuses
    # a program CPython runs, because the `try` body here does not raise. That
    # is the conservative direction and it is pinned deliberately: a rule that
    # assumed a handler is dead would report the far more common
    # `except: pass` shape as a store, which is the wrong way round.
    ("one_handler_stores_refused",
     "    try:\n        p = 1\n    except ValueError:\n        pass\n"
     "    return p\n", "refuse",
     "a handler is assumed reachable, and nothing says it will not run"),
    ("try_else_and_handler_ok",
     "    try:\n        p = 1\n    except ValueError:\n        p = 2\n"
     "    else:\n        p = 3\n    return p\n", "ok"),
    ("finally_store_dominates_ok",
     "    try:\n        return 1\n    finally:\n        p = 1\n", "ok"),
    ("finally_store_then_read_ok",
     "    try:\n        pass\n    finally:\n        p = 1\n"
     "    return p\n", "ok"),
    # The body raises on every path, so the statement after the `try` is only
    # reachable through the `finally` — and the `finally` does not store.
    ("finally_does_not_store_refused",
     "    try:\n        pass\n    finally:\n        pass\n"
     "    return p\n", "refuse"),
    # `except ... as e` binds `e` for the handler only. Treating it as defined
    # everywhere is the conservative direction (it can only ever hide a report,
    # never invent one), and this row is the pin for that decision.
    ("handler_binding_is_not_a_local_ok",
     "    try:\n        pass\n    except ValueError as e:\n"
     "        return 0\n    return 0\n", "ok"),
    ("except_star_stores_ok",
     "    try:\n        p = 1\n    except* ValueError:\n        p = 2\n"
     "    return p\n", "ok"),

    # ── `with`: the body is reached only through the item expression ───────
    ("with_body_store_dominates_ok",
     "    with sink(n) as s:\n        p = 1\n    return p\n", "ok"),
    ("with_item_read_before_store_refused",
     "    with sink(p) as s:\n        pass\n    return 0\n", "refuse"),
    ("with_alias_is_bound_in_body_ok",
     "    with sink(n) as s:\n        return s\n    return 0\n", "ok"),

    # ── `match`: a wildcard arm is irrefutable, and a missing one falls
    #    THROUGH to whatever follows, which is a path that stores nothing.
    ("match_wildcard_is_exhaustive_ok",
     "    match n:\n        case 0:\n            p = 1\n        case _:\n"
     "            p = 2\n    return p\n", "ok"),
    ("match_no_wildcard_refused",
     "    match n:\n        case 0:\n            p = 1\n        case 1:\n"
     "            p = 2\n    return p\n", "refuse"),
    ("match_capture_is_exhaustive_ok",
     "    match n:\n        case 0:\n            p = 1\n        case other:\n"
     "            p = 2\n    return p\n", "ok"),
    # A `case` with a `guard` is refutable however its pattern reads — the
    # guard is the source saying "this one might not match" — so the match
    # falls through to the code after it on a path that stores nothing.
    # CPython runs this particular program, because `case 0` takes n == 0
    # first and the guard is then always true; deciding that needs the
    # pattern-matching semantics rather than the graph, and the conservative
    # answer is the one that cannot hide a real defect.
    ("match_guarded_wildcard_refused",
     "    match n:\n        case 0:\n            p = 1\n"
     "        case _ if n:\n            p = 2\n    return p\n", "refuse",
     "a guarded case is treated as refutable, so the match can fall through"),
    ("match_wildcard_then_store_ok",
     "    match n:\n        case _:\n            p = 1\n"
     "    p = 2\n    return p\n", "ok"),
    # A `case` pattern that is a bare name nothing has bound is a CAPTURE in
    # this compiler (`fire_compiler.py`'s MatchStmt and
    # `myinterpreter.py`'s `execute_MatchStmt`), and a capture binds the
    # subject before the arm's body runs — the same shape as a `for` target and
    # a `with` alias, and the third of the three
    # `bugs/FORMAL_a_local_read_before_its_first_assignment.md` names. The arm
    # was refused for reading its own capture.
    ("match_capture_is_bound_in_its_own_arm_ok",
     "    match n:\n        case 0:\n            return 1\n        case other:\n"
     "            sink(other)\n    return 0\n", "ok"),
    # …and it is bound in THAT arm only. One case's capture is not in scope in
    # another's, which is why the names are a per-block `seed` and not more of
    # the match head's definitions: CPython raises here (`a` is not defined
    # anywhere in the harness, so `NameError`).
    ("match_capture_is_not_in_scope_in_another_arm_refused",
     "    match n:\n        case 0:\n            sink(a)\n        case other:\n"
     "            sink(other)\n    return 0\n", "refuse"),
    # THE ROW THAT PINS THE PER-ARM `seed`, and the reason it is not "add the
    # captures to the match head's definitions". Here the SECOND case is the one
    # that captures, and the first arm reads that name: the capture makes `a` a
    # local of `probe`, so CPython raises `UnboundLocalError` at `probe(0)`.
    # Put the captures on the head instead and `a` would be in scope in an arm
    # that never tried to bind it, which is the worse of the two errors — a
    # defect this analysis exists to find.
    ("a_later_case_capture_is_not_in_scope_in_an_earlier_arm_refused",
     "    match n:\n        case 0:\n            sink(a)\n        case a:\n"
     "            sink(a)\n    return 0\n", "refuse"),
    # A GUARD makes the case refutable however its pattern reads, so an EARLIER
    # case can match and the match then falls through to the code after it on a
    # path where the capture was never bound. (The guard failing does NOT undo
    # the binding — measured on CPython 3.11, `return other` after a
    # `case other if other > 5` returns the subject for every value — so the
    # path that matters is the one an earlier case takes, which is what this
    # body writes.) CPython raises `UnboundLocalError` there, because the
    # capture makes `other` a local of `probe`.
    ("match_guarded_capture_falls_through_to_a_read_refused",
     "    match n:\n        case 0:\n            sink(0)\n"
     "        case other if other > 5:\n            sink(other)\n"
     "    sink(other)\n    return 0\n", "refuse"),
    # The mirror of that row and the reason the capture is a per-arm `seed` and
    # not a match-wide definition: an EARLIER case matching means the capture
    # case is never tried, so a read after the match is a real defect even
    # though the match ends in an irrefutable capture. CPython raises
    # `UnboundLocalError` at `probe(0)` and `probe(1)`; `case other` alone is
    # not enough to make `other` dominate the join.
    ("match_capture_after_an_earlier_case_matched_refused",
     "    match n:\n        case 0:\n            sink(0)\n        case other:\n"
     "            sink(other)\n    sink(other)\n    return 0\n", "refuse"),
    # THE PIN that says `_match_case_binds` stops at a bare name on purpose.
    # `match` here is switch-style equality dispatch, not PEP 634 structural
    # pattern matching, so `case [a, b]` evaluates the list `[a, b]` and
    # compares it with `==`: `a` and `b` are READS. CPython binds them, so this
    # row is a deliberate divergence and not an oracle failure — which is
    # exactly the sort of row the fourth column exists for.
    ("match_sequence_pattern_binds_nothing_here_refused",
     "    match n:\n        case [a, b]:\n            sink(a + b)\n"
     "        case _:\n            return 0\n    return 0\n", "refuse",
     "`match` is equality dispatch in this compiler, so a pattern's "
     "sub-expressions are reads and not bindings — see `_match_case_binds`"),

    # ── `del`: removes a name from the definitely-stored set without storing
    #    anything, so a `del` on one path IS a read-before-store on the other.
    ("del_on_both_arms_then_store_ok",
     "    p = 1\n    if n:\n        del p\n    else:\n        del p\n"
     "    p = 2\n    return p\n", "ok"),
    ("del_then_read_refused",
     "    p = 1\n    del p\n    return p\n", "refuse"),
    ("del_on_one_arm_refused",
     "    p = 1\n    if n:\n        del p\n    return p\n", "refuse"),
    # `del` on an unstored name reads it, which is this same defect.
    ("del_of_unstored_refused",
     "    del q\n    return 0\n", "refuse"),

    # ── `return` / `raise` terminate: nothing after them is reached ────────
    ("code_after_return_is_unreachable_ok",
     "    return 0\n    p = 1\n    return p\n", "ok"),
    # A `raise` TERMINATES: nothing after it is reached, so a store after it
    # is a store on the only path that arrives there. With no `else` the `if`'s
    # false edge is the second path, and it reaches the same store.
    ("raise_terminates_and_the_false_edge_still_stores_ok",
     "    if n:\n        raise ValueError()\n    p = 1\n    return p\n",
     "ok"),
    # Code after a `raise` is unreachable, and an unreachable block keeps every
    # name: there is nothing to read an unstored value. The walk reports only
    # what a REACHABLE read would have to mean, which is the same top-
    # initialization the fixpoint uses and the reason it is the safe direction.
    ("code_after_raise_is_unreachable_ok",
     "    raise ValueError()\n    return q\n", "ok"),

    # ── THE ENTRY BLOCK MUST NOT HAVE A SECOND SUCCESSOR ──────────────────
    #
    # `_build_cfg` used to end with `entry.succs += run(body, …)`, i.e. an edge
    # from the function's ENTRY block to whichever block the body's last
    # statement falls out of. Every one of those blocks is already reachable —
    # the body was emitted with the entry as its pending predecessor — so the
    # extra edge was a path from function entry to the final join that passes
    # through nothing the body stores, and the fixpoint's intersection over
    # that join's predecessors threw the body's definitions away.
    #
    # The refusal it produced named CPython's `UnboundLocalError` for programs
    # CPython runs, and it fired on 54 functions across 26 files of
    # `std/{builtin,collections,memory,algorithm,bit}` alone — including
    # `_heapify_up`/`_heapify_down` in `collections/binary_heap.mojo` and every
    # one of `builtin/sort.mojo`'s five sort helpers, each of which stores the
    # name on the only path there is.
    #
    # The edge only appeared when the body FALLS OFF THE END — `run` returns
    # `[]` for a body whose last statement is a `return` or a `raise`, and then
    # there is nothing to add — so the three rows below all end in an
    # expression statement rather than a `return`, which is also the shape
    # every one of the real refusals has. The refusal rows above are what keep
    # the fix from being a loosening: the entry edge was the only spurious
    # edge, and the loop HEAD's edge to the join is still there.
    ("store_before_a_loop_then_read_after_it_ok",
     "    q = 1\n    while n > 0:\n        n = n - 1\n    sink(q)\n", "ok"),
    ("store_before_a_branch_then_read_after_it_ok",
     "    q = 1\n    if n:\n        q = 2\n    sink(q)\n", "ok"),
    ("for_target_is_stored_for_its_own_body_ok",
     "    for i in range(n):\n        sink(i)\n", "ok"),

    # ── names the check must NOT ask about ───────────────────────────────
    # A comprehension's target is bound inside its own scope, so a read of it
    # is not a read of an unstored local — the row a flat node walk gets
    # wrong, and it was wrong here: the first version of the check refused it.
    ("comprehension_target_ok",
     "    return [i + 1 for i in range(3)]\n", "ok"),
    # A `global` moves the storage out of the frame entirely, so this check
    # must not ask about the name. CPython's own answer here is a NameError,
    # which is a different question — name resolution, owned by
    # `check_module_symbols` — and reporting it from here would be a second
    # and worse message about the same name.
    ("global_declaration_ok",
     "    global p\n    return p\n", "ok",
     "a `global` name's storage is not this frame's; CPython's NameError is a "
     "name-resolution question this check does not own"),
    ("nested_def_with_its_own_params_ok",
     "    def inner(k):\n        return k + 1\n    return inner(n)\n", "ok"),
    # A nested definition's body is a DIFFERENT frame with its own parameters,
    # and its locals are not this function's. Walking it against this
    # function's store set is how a local of the inner function got reported
    # against the outer frame.
    ("nested_def_is_another_frame_ok",
     "    def inner():\n        m = 1\n        return m\n"
     "    return inner()\n", "ok"),
]


def cpython_raises(body: str, value: int) -> bool:
    """Whether CPython raises UnboundLocalError/NameError for this body.

    Run in a SUBPROCESS, because the question is what CPython's own compiler
    says about the function, and a name the analysis believes is a local is
    not a local here: a module-level binding for it in this harness would make
    CPython resolve it as a global and the oracle would answer "no" for every
    case. So the source is exactly the case's body plus a `sink` and a call at
    the bottom, with nothing else in scope.

    `NameError` counts as well as `UnboundLocalError` because a `global`
    declaration turns the same defect into a `NameError`, and the case that
    cares about it says so in its `diverges` note.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write("def sink(x):\n    return x\n\ndef probe(n):\n" + body
                + f"\nprobe({value})\n")
        path = f.name
    try:
        p = subprocess.run([sys.executable, path], capture_output=True,
                           text=True, timeout=20)
    except subprocess.TimeoutExpired:
        # A case whose body does not terminate is a mistake in the CASE, not
        # an answer from CPython, and answering "did not raise" for it would
        # quietly turn a hung oracle into a verdict.
        raise AssertionError(f"probe({value}) did not terminate under CPython")
    finally:
        os.unlink(path)
    return ("UnboundLocalError" in p.stderr or "NameError" in p.stderr)


def the_function(stmts):
    for s in stmts:
        if isinstance(s, F.FunctionDef) and s.name == "probe":
            return s
    raise AssertionError("the case source has no `probe` function")


# (name, body, what the entry block's successor list must be)
#
# `entry_shape` pins the GRAPH rather than a verdict, because the defect was in
# the graph and every verdict above can be satisfied by a rule that happens to
# give the right answer for the wrong reason. The entry block holds no
# statements, so its only successor is the block the body's FIRST statement
# opens — one successor, whatever the body is, and never a block further down.
#
# `read_before_store`'s whole argument is "a store dominates a read only when
# every path from the entry to the read passes one", so an edge that is not a
# path the program has is not a conservative extra edge: it is a claim that
# control reaches the end of the function having stored nothing, which is a
# program CPython does not have.
ENTRY_SHAPES = [
    ("entry_reaches_only_the_first_statement",
     "    q = 1\n    return q\n", [1]),
    ("entry_does_not_reach_the_join_after_a_loop",
     "    q = 1\n    while n > 0:\n        n = n - 1\n    sink(q)\n", [1]),
    ("entry_does_not_reach_the_join_after_a_branch",
     "    q = 1\n    if n:\n        q = 2\n    sink(q)\n", [1]),
    ("entry_does_not_reach_the_loop_target_read",
     "    for i in range(n):\n        sink(i)\n", [1]),
    ("a_body_of_only_pass_still_has_one_successor",
     "    pass\n", [1]),
]


def check_entry_shape() -> list:
    """Every failure in ENTRY_SHAPES, as strings."""
    bad = []
    for name, body, want in ENTRY_SHAPES:
        fn = the_function(parse_module("def probe(n):\n" + body,
                                       filename=f"{name}.mojo"))
        blocks, entry = M._build_cfg(fn.body)
        got = blocks[entry].succs
        if got != want:
            bad.append(f"{name}: the entry block's successors are {got}, "
                       f"not {want}")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    passed = failed = 0
    for case in CASES:
        name, body, expect = case[0], case[1], case[2]
        # The optional fourth column is a DELIBERATE divergence: this analysis
        # and CPython answer differently, the difference is understood, and the
        # oracle must not report it as a bug in either direction. Every one of
        # them is a case where the analysis refuses something CPython runs, or
        # stays silent about something CPython rejects for a reason that is not
        # about the frame's storage.
        diverges = case[3] if len(case) > 3 else None
        details = []
        fn = None
        try:
            fn = the_function(parse_module("def probe(n):\n" + body,
                                           filename=f"{name}.mojo"))
        except Exception as exc:                        # noqa: BLE001
            details.append(f"the Mojo parser rejected the case: {exc!r}")
        verdict = None
        if fn is not None:
            found = M.read_before_store(fn)
            verdict = "refuse" if found else "ok"
            if verdict != expect:
                where = (f" (it reported {found[0]!r} at line {found[1]})"
                         if found else "")
                details.append(f"the analysis says {verdict!r} and the case "
                               f"expects {expect!r}{where}")
            try:
                raised = [v for v in PROBE_VALUES if cpython_raises(body, v)]
            except AssertionError as exc:
                raised = []
                details.append(str(exc))
            if not diverges:
                if verdict == "refuse" and not raised:
                    details.append(
                        "the analysis refuses, but CPython ran this without "
                        f"UnboundLocalError for any of {PROBE_VALUES} — a "
                        "refusal the language would not have made")
                if verdict == "ok" and raised:
                    details.append(
                        f"CPython raises UnboundLocalError at probe({raised[0]})"
                        " and the analysis let it through — the check missed a "
                        "real defect")
        if details:
            failed += 1
            print(f"  FAIL  {name}: {'; '.join(details)}")
        else:
            passed += 1
            if args.verbose:
                mark = f" [diverges: {diverges}]" if diverges else ""
                print(f"  PASS  {name} ({expect}){mark}")
    for problem in check_entry_shape():
        failed += 1
        print(f"  FAIL  entry-shape: {problem}")
    print(f"read-before-store: PASS={passed} FAIL={failed} "
          f"({len(ENTRY_SHAPES)} graph shapes)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
