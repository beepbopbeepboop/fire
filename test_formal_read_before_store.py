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
    # ── a `try`'s `else` runs ONLY when the body completed ─────────────────
    # The two rows below are the fix that `try_else_and_handler_ok` could not
    # see, because there every arm stores and the answer is "ok" whichever way
    # the clause is reached. `else` is entered from the HEADER (so it is one more
    # arm of the try, hanging off `t.index`) and the header reaches it on
    # exactly the path the language SKIPS it — the one where the body raised. So
    # every name the body stores lost its dominance inside `else`, and a program
    # CPython runs was refused with a sentence claiming CPython raises
    # `UnboundLocalError` for it.
    #
    # Measured on `test_struct_formal.py:603`, where `out = build_module_dylib(…)`
    # is in the `try` and `os.path.isfile(out)` is in the `else` — the ordinary
    # "build it, and check it only on the path that succeeded" shape, which is
    # what `try/except/else` is FOR.
    ("try_else_clause_runs_only_when_the_body_completed_ok",
     "    try:\n        p = 1\n    except ValueError:\n        pass\n"
     "    else:\n        sink(p)\n    return 0\n", "ok"),
    # …and the store still has to dominate INSIDE the clause: a store in only
    # one arm of the body is not a dominating store, and `else` reads it. This
    # is the row that says the fix removed an edge rather than the check.
    ("try_else_clause_still_refuses_an_unstored_read",
     "    try:\n        if n:\n            p = 1\n    except ValueError:\n"
     "        pass\n    else:\n        sink(p)\n    return 0\n", "refuse"),
    # ── a `finally` and every point the body LEAVES EARLY ──────────────────
    # The clause runs on every way out, including an exception, and that one
    # path is not one of the arms — so it was modelled separately, as a fallback
    # used when the body has no fall-through exit, and it pointed at the try's
    # HEADER. The header is not a point that can raise: nothing in `try:`
    # evaluates anything before the body, so the earliest point that can is the
    # body's first block, and a store there dominates the clause. This is the
    # "build it, and clean up whatever happened" shape
    # (`tools/mem_slope.py:180` is the measured refusal: `exes = []` in the
    # body, `for e in exes: unlink(e)` in the `finally`).
    ("try_finally_clause_reads_what_the_body_stored_ok",
     "    try:\n        exes = []\n        sink(n)\n        return 0\n"
     "    finally:\n        sink(exes)\n", "ok"),
    # …and a name bound LATER in the body is not in the clause's IN set: the
    # clause is emitted at every point the body leaves early (`_flush_pending_
    # finally` walks the pending frames at the `return`/`raise`/`break`/
    # `continue` site), so it reads whatever the register held at THAT point.
    ("try_finally_clause_still_refuses_a_later_store",
     "    try:\n        p = 1\n        if n:\n            q = 2\n"
     "    finally:\n        sink(q)\n    return 0\n", "refuse"),
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
    # ── the rule that replaced "the body may have raised", in both directions ──
    #
    # The predecessor rule used to be `arm_exits or [body_first]` — the arms'
    # fall-through, or the body's FIRST block when the body had no fall-through
    # at all — and the reason it gave was an EXCEPTION. This backend has none:
    # `_emit_try` skips the handler arms and `RaiseStmt` flushes the pending
    # finallys and then `exit(1)`s, so that path does not exist in the emitted
    # image at all.
    #
    # What DOES exist is the early-exit flush, and the row below is the program
    # it hid: `body_exits` is non-empty here (the `if`'s false arm falls
    # through), so the old rule added NO edge and the build accepted it. The
    # arm64 image ran it as
    #
    #     8432255232        # sink's argument: a word nobody wrote
    #     exit 100          # CPython: UnboundLocalError, exit 1
    #
    # which is the worst outcome this path has — right-looking, exits 0, and the
    # number changes with the build. `test_formal_run.py` carries the same
    # program as a `refuse:` row on both architectures.
    ("finally_clause_runs_at_every_point_the_body_leaves_early_refused",
     "    try:\n        if n > 0:\n            return 100\n        v = 7\n"
     "    finally:\n        sink(v)\n    return 0\n", "refuse"),
    # …and the inverse, which is the direction a fix like this can get wrong:
    # when the clause's only entries are points that HAVE stored the name, it
    # is a dominating store and the check must stay silent. The `return 0` is
    # after `v = 7` on every path, so the clause reads a bound name.
    ("finally_after_every_store_is_still_ok",
     "    try:\n        v = 7\n        if n > 0:\n            return 100\n"
     "        return 0\n    finally:\n        sink(v)\n", "ok"),
    # A `break` that ESCAPES the try flushes the clause (`_flush_pending_
    # finally(self._loops[-1]["fin_depth"])` with the try's frame below that
    # depth), and it does so before the store — so the clause reads `v` unbound
    # for `n == 0`, which is the one probe value that breaks out on the first
    # iteration.
    ("break_out_of_the_try_reaches_the_clause_refused",
     "    for i in range(3):\n        try:\n            if n > 0:\n"
     "                break\n            v = 7\n        finally:\n"
     "            sink(v)\n    return 0\n", "refuse"),
    # …and a `break` out of a loop the BODY opened does not: control stays
    # inside the body and reaches the clause by falling through, past the store.
    # The row that says the two are not the same edge.
    ("break_inside_the_try_body_does_not_reach_the_clause_ok",
     "    try:\n        v = 7\n        for i in range(3):\n"
     "            if n > 0:\n                break\n        sink(n)\n"
     "    finally:\n        sink(v)\n    return 0\n", "ok"),
    # ── the clause's own fall-through, and the dead code after it ──────────
    # When neither the body nor the `else` can fall through, `_emit_try`
    # suppresses the clause's fall-through (`need_fallthrough = False`, once a
    # `return`/`raise` has flushed the frame) and the statement after the try
    # is DEAD. The old rule judged it on the state at the body's first block,
    # which refused `try: … total = … / finally: cleanup` then `print(total)`
    # on seven files of this repository — every one of them a program CPython
    # runs, because nothing ever reaches the `print`. `_definitely_stored`
    # top-initializes a block with no predecessor, so an empty `pending` here
    # answers it the safe way.
    ("dead_code_after_an_always_returning_try_is_not_a_refusal_ok",
     "    try:\n        total = 1\n        if n:\n            total = 2\n"
     "        return 0\n    finally:\n        sink(n)\n    return total\n",
     "ok"),
    # …and the LIVE version of the same shape: the body falls through, so the
    # clause is reached and `total` dominates it.
    ("a_fall_through_body_still_reaches_the_clause_ok",
     "    try:\n        total = 1\n        if n:\n            total = 2\n"
     "        sink(n)\n    finally:\n        sink(n)\n    return total\n",
     "ok"),
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
# ── the TWO shapes a trailing statement can take ───────────────────────
    # One defect, `_build_cfg` adding its `run`'s return value to the ENTRY
    # block's successors, so the entry pointed at a block at the END of the
    # body as well as the first — a path the source does not have. The fixpoint
    # intersects a join's IN over its predecessors and the entry's OUT is only
    # the parameter names, so every local stored before the trailing statement
    # dropped out of that statement's own regions and a read there looked
    # unstored. The check `ENTRY_SHAPES` below pins the graph itself; the two
    # groups here pin the two shapes a LAST statement can have when the edge had
    # something to attach to, which is what makes the hole invisible in every
    # case above (they all end in `return`, and the `ReturnStmt` arm makes `run`
    # return `[]`).

    # ── (a) the LAST statement is an expression, not a control-flow statement
    # Every case above ends in `return`, which is why this hole survived: the
    # `ReturnStmt` arm makes `_build_cfg`'s `run` return `[]`, so the entry
    # block's extra edge had nothing to attach to. A function whose last
    # statement is `print(n)` or a bare call is ordinary, and the entry block
    # was given a second, fictitious edge straight to that final block — so the
    # fixpoint intersected the body's whole path with the entry's OUT set (the
    # parameter seed, and nothing else) and any name the body stored
    # unconditionally read as never stored. It refused five `struct.pack`
    # programs in `test_struct_formal.py` for `n = 0` three lines above the
    # `print(n)`.
    ("tail_expression_statement_ok",
     "    q = 1\n    sink(q)\n", "ok"),
    # The shape that actually fired: a loop whose body may never run, and a
    # store BEFORE it, then a read in the trailing expression statement.
    ("tail_expression_after_loop_ok",
     "    n = 0\n    i = 0\n    while i < 3:\n        n = n + i\n"
     "        i = i + 1\n    sink(n)\n", "ok"),
    # The same trailing statement with a store in only ONE arm is still a real
    # defect, so the fix is not a blanket "the entry edge goes away" — this is
    # the row that says the analysis still refuses here.
    ("tail_expression_only_arm_store_refused",
     "    if n:\n        p = 1\n    sink(p)\n", "refuse"),
    ("tail_expression_after_a_returning_if_ok",
     "    q = 1\n    if n:\n        return 0\n    sink(q)\n", "ok"),
    ("tail_expression_after_try_finally_ok",
     "    q = 1\n    try:\n        return 0\n    finally:\n        pass\n"
     "    sink(q)\n", "ok"),

    # ── (b) the LAST statement is itself a control-flow statement ───────────
    # `_build_cfg` used to add its `run`'s return value to the ENTRY block's
    # successors, which asserted a path from the function's first instruction
    # into the tail of the body. The fixpoint pays for that edge, because the
    # entry's OUT is only the parameter names: any region the trailing control
    # statement opened had its IN intersected with the parameters, so every
    # local stored before the statement dropped out of it and a read inside that
    # statement's own arms looked unstored. Every program in this group is
    # ordinary and every one of them was REFUSED.
    #
    # Measured on the corpus, not only here: it is what `re.mojo`'s `_p_alt`
    # was reported for, whose `while 1:` is its last statement and which says
    # `pend = entry` three lines above the read it was reported for. Taking `re`
    # out of the backend takes out every file that imports it.
    #
    # The shape is not "a loop reads a local" — it is TWO conditions together:
    # the body's LAST statement is a control-flow statement, AND at least one
    # path FALLS OUT of it. The second half is not a detail: `run` returns []
    # when every arm of the trailing statement terminates (`return`, `raise`,
    # `break` all give no fall-through exit), so there is nothing to edge the
    # entry to and the bug cannot fire. A body whose trailing `if` returns from
    # both arms builds today and built before the fix, which is measured and is
    # pinned below — a rule stated only in its coarse form sends the next reader
    # to a program it does not reproduce on.
    #
    # Adding a statement AFTER the loop is the smallest thing that hides it,
    # which is exactly the accidental difference between this group and the
    # ones above it — and the same accident makes group (a) invisible to (b).
    ("trailing_while_ok",
     "    p = 1\n    while n:\n        q = p\n        n = n - 1\n", "ok"),
    # `while 1:` is the shape the corpus uses most (a loop whose exit is a
    # `break` or a `return`), and it is a separate CFG path because the loop
    # always runs at least once.
    ("trailing_while_true_ok",
     "    p = 1\n    while 1:\n        q = p\n        n = n - 1\n        "
     "if n < 0:\n            break\n", "ok"),
    ("trailing_for_ok",
     "    p = 1\n    for i in range(n):\n        q = p\n", "ok"),
    ("trailing_if_ok",
     "    p = 1\n    if n:\n        q = p\n", "ok"),
    ("trailing_if_else_ok",
     "    p = 1\n    if n:\n        q = p\n    else:\n        r = p\n", "ok"),
    ("trailing_try_ok",
     "    p = 1\n    try:\n        q = p\n    except:\n        r = p\n", "ok"),
    ("trailing_match_ok",
     "    p = 1\n    match n:\n        case 0:\n            q = p\n", "ok"),
    ("trailing_with_ok",
     "    p = 1\n    with sink(n) as s:\n        q = p\n", "ok"),
    # And the same bodies still REFUSE when the name really is unstored: the
    # fix removed an edge that asserted a path the source does not have, not
    # the check itself.
    ("trailing_control_flow_still_refuses_an_unstored_read",
     "    while n:\n        q = q\n        n = n - 1\n", "refuse"),
    ("trailing_control_flow_still_refuses_one_arm_store",
     "    if n:\n        p = 1\n    else:\n        q = p\n", "refuse"),
    # The OTHER direction of the rule's second condition: a trailing control
    # statement whose every arm TERMINATES produced no fall-through exit, so
    # the entry had nothing spurious to point at and the old code refused
    # nothing. Pinned so the rule is not restated in its coarse form.
    ("trailing_if_whose_arms_all_return_is_the_other_shape",
     "    p = 1\n    if n:\n        return p\n    return 0\n", "ok",
     "every arm terminates, so `run` returns [] and there is no spurious entry "
     "edge to remove — this is the case the coarse form of the rule gets wrong"),
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

# (name, body, the block that holds the `sink` inside the `else`)
#
# The same argument as ENTRY_SHAPES, for the OTHER fictitious edge this
# analysis had: `else` hung off the try's HEADER, and the header reaches it on
# the path where the body raised — which is the one path on which the language
# does not run `else` at all. So `else` is entered from the BODY's fall-through
# exits and from nothing else, and the block holding its first statement says
# which: its `preds` must not contain the try's header.
#
# The index is the block that holds `sink(p)`, which is what makes this a
# statement about the graph rather than about a verdict: a rule that got the
# right answer by leaving `else` unreachable would pass every row in CASES.
TRY_ELSE_SHAPES = [
    # 0 entry, 1 the try (header), 2 the body's store, 3 the handler,
    # 4 the `else`'s `sink(p)`.
    ("try_else_is_entered_from_the_body_not_the_header",
     "    try:\n        p = 1\n    except ValueError:\n        pass\n"
     "    else:\n        sink(p)\n", 4),
    # 0 entry, 1 `q = 1`, 2 the try (header), 3 the body's `if`, 4 `p = 1`,
    # 5 the handler, 6 the `else`'s `sink(p)`: the clause is entered from the
    # body's own exits — the branch's false edge and its storing arm — and from
    # neither the header nor anything outside the body.
("try_else_is_entered_from_every_body_exit",
     "    q = 1\n    try:\n        if n:\n            p = 1\n"
     "    except ValueError:\n        pass\n    else:\n        sink(p)\n",
      6),
]


# (name, body, the block that holds the `sink` inside the `finally`, its exact
#  predecessor list, whether the statement after the try is DEAD)
#
# The same argument as the two groups above, for the `finally` clause — and the
# group that matters most, because the rule it pins was wrong in the direction
# that produces a silently incorrect binary rather than a refusal.
#
# `_flush_pending_finally` emits a pending clause's statements AT the
# `return`/`raise`/`break`/`continue` site, so the clause is entered from every
# point the try statement leaves early, not only from the paths that fall out of
# it. The predecessors below are that set, read off the graph, and the
# `dead_after` column is the other half of the rule: `_emit_try` suppresses the
# clause's own fall-through once an early exit has flushed the frame
# (`need_fallthrough = False`), so with no falling-through body path nothing
# follows the clause and the code after the statement is unreachable.
#
# What the rule replaced was `arm_exits or [body_first]`, justified by "the body
# may have raised". This backend has no unwinder — `_emit_try` skips the handler
# arms and `RaiseStmt` flushes and then `exit(1)`s — so that edge was a path
# the emitted image does not have, and the real one was missing.
FINALLY_SHAPES = [
    # 0 entry, 1 the try (header), 2 the body's `if`, 3 `return 100`,
    # 4 `v = 7`, 5 the clause's `sink(v)`, 6 `return 0`.
    #
    # The clause is entered from the `return 100` (an early exit, before the
    # store) and from the storing arm's fall-through. It is NOT entered from
    # block 2 — the point the old rule used — and `v` is therefore not in its IN
    # set, which is what the build refuses.
    ("finally_is_entered_from_the_early_exit_not_the_body_first",
     "    try:\n        if n > 0:\n            return 100\n        v = 7\n"
     "    finally:\n        sink(v)\n    return 0\n", 5, [3, 4], False),
    # 0 entry, 1 the try, 2 `v = 7`, 3 the body's `if`, 4 and 5 the two
    # `return`s, 6 the clause. Both entries are AFTER the store, so `v` is in
    # the clause's IN set and the check is silent — the direction a fix that
    # only ever adds predecessors gets wrong.
    ("finally_after_every_early_exit_is_a_dominating_store",
     "    try:\n        v = 7\n        if n > 0:\n            return 100\n"
     "        return 0\n    finally:\n        sink(v)\n", 6, [4, 5], True),
    # 0 entry, 1 the try, 2 `total = 1`, 3 the body's `if`, 4 `total = 2`,
    # 5 `return 0`, 6 the clause. The body cannot fall through, so nothing
    # follows the clause: `return total` after the statement is dead code, and
    # judging it on the state at `total = 1` is what refused `try: … total = … /
    # finally: cleanup` then `print(total)` on seven files.
    ("nothing_follows_a_finally_whose_body_cannot_fall_through",
     "    try:\n        total = 1\n        if n:\n            total = 2\n"
     "        return 0\n    finally:\n        sink(n)\n    return total\n",
     6, [5], True),
]


def check_try_else_shape() -> list:
    """Every failure in TRY_ELSE_SHAPES, as strings."""
    bad = []
    for name, body, want in TRY_ELSE_SHAPES:
        fn = the_function(parse_module("def probe(n):\n" + body,
                                       filename=f"{name}.mojo"))
        blocks, _entry = M._build_cfg(fn.body)
        head = next(b.index for b in blocks
                    if b.stmts and type(b.stmts[0]).__name__ == "TryStmt")
        block = blocks[want]
        if head in block.preds:
            bad.append(f"{name}: the `else` block {want} has the try's header "
                       f"{head} as a predecessor, so the clause is reachable "
                       f"on the path where the body raised — the one path the "
                       f"language skips it on")
        if not block.preds:
            bad.append(f"{name}: the `else` block {want} has no predecessor at "
                       f"all, so the fixpoint reads it as unreachable and the "
                       f"clause is never checked")
    return bad


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


def check_finally_shape() -> list:
    """Every failure in FINALLY_SHAPES, as strings."""
    bad = []
    for name, body, clause, want_preds, dead_after in FINALLY_SHAPES:
        fn = the_function(parse_module("def probe(n):\n" + body,
                                       filename=f"{name}.mojo"))
        blocks, _entry = M._build_cfg(fn.body)
        block = blocks[clause]
        if sorted(block.preds) != sorted(want_preds):
            bad.append(f"{name}: the `finally` clause block {clause} is entered "
                       f"from {sorted(block.preds)}, not {sorted(want_preds)}")
        if not block.preds:
            bad.append(f"{name}: the `finally` clause block {clause} has no "
                       f"predecessor, so the fixpoint reads it as unreachable "
                       f"and the clause is never checked — an early exit in the "
                       f"body reaches it")
        head = next(b.index for b in blocks
                    if b.stmts and type(b.stmts[0]).__name__ == "TryStmt")
        body_first = next(b.index for b in blocks[head + 1:]
                          if b.preds == [head])
        if body_first in block.preds:
            bad.append(f"{name}: the `finally` clause is entered from the body's "
                       f"FIRST block {body_first}, which is the fallback the "
                       f"exception reading used — this backend has no unwinder, "
                       f"so no point can raise into the clause")
        # The clause's own fall-through reaches the statement after the try, and
        # `_emit_try` emits it only where the body falls through. So when every
        # body path leaves early, nothing follows the clause and the dead code
        # after the statement is not judged on any body's state; when the body
        # can fall through, something does.
        follows = [b.index for b in blocks if block.index in b.preds]
        if dead_after and follows:
            bad.append(f"{name}: blocks {follows} follow the `finally` clause, "
                       f"but no body path falls through, so `_emit_try` "
                       f"suppresses the clause's fall-through and the code after "
                       f"the statement is dead")
        if not dead_after and not follows:
            bad.append(f"{name}: nothing follows the `finally` clause, so the "
                       f"statement after the try reads as unreachable — the "
                       f"body falls through and the clause's fall-through is "
                       f"emitted")
    return bad


# ── WHICH NAMES THE CHECK MAY ASK ABOUT ──────────────────────────────────
#
# Everything above asks `model.read_before_store` about a function in
# isolation, and that is the whole analysis: given a set of names this function
# could have stored, which does it read first? The BUILD asks a narrower
# question before it gets there — `formal/build.py::_unstored_read` intersects
# the caller's `placed` set with the names the function ITSELF binds, and
# `placed` is a union of several kinds of home (a parameter, a local, a comptime
# binding, a struct TYPE, every function this image defines, a specialization's
# base, an imported module). Taking all of it as "a local this function stores
# somewhere" made the check refuse a read of a name no statement of the body
# has anything to do with.
#
# It needs its own rows because the failure is INVISIBLE to the ones above: each
# of them passes `placed=None`, so they would all still pass with the old
# intersection. These call the build's own function, with the build's own
# recipe for `placed`, on a MODULE — the defect needs a second definition in
# the unit for `_callee_defs` to have anything to add.
OWN_NAMES = [
    # (name, source, the name reported, or None)
    # A module-level FUNCTION handed to a call as a value: `ex.submit(run_one,
    # mode, f)` in `test_stdlib.py:55` is the real one. `run_one` is in `placed`
    # because `_callee_defs` puts every function this image defines there (so
    # that CALLING one needs no local), and the read-before-store check read
    # that as "the body assigns it somewhere" and reported it. The message
    # claimed CPython raises `UnboundLocalError` for a program it runs.
    ("a_module_function_read_as_a_value_is_not_an_unstored_local",
     "def helper() -> Int:\n    return 1\n\ndef probe():\n    f = helper\n"
     "    return f\n", None),
    # The same reasoning for a TYPE: `struct_names` is in `placed` because
    # `S.x` and `S()` are not reads of a value, and a type has no register at
    # all — so "the register allocator gave it a home" was never true of it.
    ("a_type_read_as_a_value_is_not_an_unstored_local",
     "struct S:\n    x: Int\n\ndef probe():\n    return S\n", None),
    # A `*args` / `**kwargs` parameter is stored by the CALLER, exactly like a
    # positional one, and `incoming_args` spells it the way the signature does —
    # `*args`, stars included — so subtracting the parameters left the bare name
    # in the candidate set. Latent rather than visible: the build refuses a
    # variadic read by name first (`_refuse_variadic_reads`), which is why this
    # row is a unit row and not a build row.
    ("a_variadic_parameter_is_not_an_unstored_local",
     "def probe(*args, **kw):\n    return sink(args)\n", None),
    # …and the ordinary parameter, which the same subtraction handles, so the
    # rows above cannot be a blanket "never ask about a parameter".
    ("a_runtime_parameter_is_not_an_unstored_local",
     "def probe(q):\n    return q\n", None),
    # THE DEFECT IS STILL FOUND. A name the function binds and reads before
    # storing is the whole subject, and it is in `own` for the same reason every
    # other case above is.
    ("a_self_reference_is_still_an_unstored_read",
     "def probe():\n    p = p + 1\n    return p\n", "p"),
    ("an_augmented_read_is_still_an_unstored_read",
     "def probe(n):\n    total += n\n    return total\n", "total"),
]


def check_own_names() -> list:
    """Every failure in OWN_NAMES, as strings."""
    import formal.build as B
    bad = []
    for name, src, want in OWN_NAMES:
        stmts = parse_module(src, filename=f"{name}.mojo")
        functions, structs, _syms, _slots = B._prepare_functions(stmts)
        by_name = {s.name for s in structs}
        callees = set(B._callee_defs(functions))
        for fn in functions:
            if fn.name != "probe":
                continue
            shape = M.function_param_shape(fn)
            placed = {n for n, _t in shape.fixed}
            placed |= {shape.vararg, shape.kwarg}
            placed.discard(None)
            placed |= B._names_bound_in(fn)
            placed |= B._comptime_bound_names(fn)
            placed |= by_name
            placed |= callees
            frame_slots = dict(getattr(fn, "_frame_slots", None) or {})
            hit = B._unstored_read(fn, placed, frame_slots)
            got = None if hit is None else hit[0]
            if got != want:
                bad.append(f"{name}: the build's `_unstored_read` reported "
                           f"{got!r} for probe, not {want!r}")
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
    for problem in check_try_else_shape():
        failed += 1
        print(f"  FAIL  try-else-shape: {problem}")
    for problem in check_finally_shape():
        failed += 1
        print(f"  FAIL  finally-shape: {problem}")
    for problem in check_own_names():
        failed += 1
        print(f"  FAIL  own-names: {problem}")
    print(f"read-before-store: PASS={passed} FAIL={failed} "
          f"({len(ENTRY_SHAPES)} graph shapes, "
          f"{len(TRY_ELSE_SHAPES)} try/else graph shapes, "
          f"{len(FINALLY_SHAPES)} finally graph shapes, "
          f"{len(OWN_NAMES)} which-names rows)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
