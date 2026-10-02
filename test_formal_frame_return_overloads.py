#!/usr/bin/env python3
"""The holder fixpoint TERMINATES, and an overloaded name gets ONE answer.

`std/python/bindings.mojo` used to wedge the arm64 formal build at a flat
0.06 GB with no growth — 850 s and still going, with the sweep's per-file `-t 30`
the only bound on it. That hang had a specific cause, and both halves of the fix
are pinned here: the cause, and the two properties the fix rests on.

**The hang.** It is not a slow build and not an allocator
blow-up; it is a loop, and the loop is in `formal/build.py`'s holder fixpoint.
`returns_frame` — "which functions return a frame address, and of which struct" —
was keyed by `fn.name` and WRITTEN by every definition under that name.
`std/python/bindings.mojo` declares `PythonTypeBuilder.def_py_init` twice, one
overload ending `return self` and the other
`return self.def_py_init[…](…)`, so the two definitions had different answers:
each pass one stored its struct in the shared slot and the other popped it,
`changed` went true on both, and the inner `while changed:` never ended.
Measured on the real file: 7819 passes and 4.1 M node walks in 20 s, still
going; on the fifteen-line program in `OVERLOAD_DISAGREES` below, the
pre-fix build does not return at all (verified by running the pre-fix
`formal/build.py` under a wall clock — it is still running when the clock runs
out).

**What the fix is.** The per-function table is keyed by `_fn_key` like every
other per-function table in that analysis, and the by-name question a call site
asks is answered by `_returns_frame_by_name`, which is a JOIN over a name's
definitions and refuses the names whose definitions disagree.

**Why the disagreement is a refusal and not a choice.** Both answers are wrong
silently: answer "frame" at every call site and the definition that returns a
word leaves the caller's reserved block unwritten; answer "word" and the
definition that returns a frame copies through a block address its caller never
passed. So `model.frame_return_overloads_disagree_refusal` names both
definitions and what each returns, and the build stops. Before the fix that
name did not produce a refusal — it produced the hang, or, when the order of
definitions happened to suit, an image that was right by luck.

**The backstop.** The fixpoint's inner loop had no bound, and the outer loop's
(`_HOLDER_FIXPOINT_ROUNDS`) cannot fire while the inner one is running — which
is why a non-terminating fixpoint reached a hang rather than the documented
refusal. `_holder_state` is the certificate: a pass that reports progress and
leaves every table it decides from exactly as it found it cannot be followed by
a pass that settles. The refusal path itself is not reachable by any program
now that the join is a join, so what is asserted here is the certificate's
content sensitivity, not the raise.

Usage:
    python3 test_formal_frame_return_overloads.py [-v]
"""
import argparse
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fire_compiler as F  # noqa: E402
import formal.build as B  # noqa: E402
import formal.model as M  # noqa: E402

FIRE = os.path.join(HERE, "fire.py")

# A build that has not terminated in this long is a hang whatever it is doing.
# Generous, because a loaded machine is not the subject: the pre-fix loop here
# runs for hours, and a fix that merely made it 20x faster would still be a hang.
BUILD_BUDGET_SECONDS = 90

# The hang, in fifteen lines. The overload is a comptime-parameter pair because
# that is the shape the language spells overloads in AND the shape
# `test_formal_run.py`'s `OVERLOAD_LAYOUT_CASES` already established this
# compiler supports: two definitions of one name, both in the image, both
# reachable by name. A same-name pair differing only in ARITY is not the shape —
# dispatch resolves it to one definition by argument count and never gets to the
# question (`call R_get(): missing required argument 'k'`).
OVERLOAD_DISAGREES = """\
struct R:
    var a: Int
    var b: Int

def give(self: R) -> Int:
    return self

def give[K: Copyable](self: R) -> Int:
    return self.a + 1

def main(n: Int) -> Int:
    var r = R()
    r.a = 7
    r.b = 8
    return r.a * 10 + r.b
"""

# The same pair where BOTH definitions return a frame of the SAME struct: no
# disagreement, so no refusal, and the by-name view answers. This is the case
# that would break if the join were "absent whenever a name is overloaded" —
# which is the shape of the fix that terminates by refusing everything.
OVERLOAD_AGREES = """\
struct R:
    var a: Int
    var b: Int

def give(self: R) -> Int:
    return self

def give[K: Copyable](self: R) -> Int:
    return self

def main(n: Int) -> Int:
    var r = R()
    r.a = 7
    r.b = 8
    var s = give(r)
    return s.a * 10 + s.b
"""


def build(source, name, tmpdir, backend="arm64"):
    """`(returncode, output)` from a real `fire.py build --formal`."""
    path = os.path.join(tmpdir, name + ".mojo")
    with open(path, "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, f"{name}.{backend}")
    import subprocess
    proc = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         f"--backend={backend}", "-o", out, path],
        capture_output=True, text=True, timeout=BUILD_BUDGET_SECONDS)
    return proc.returncode, (proc.stdout + proc.stderr).strip(), out


def run(image):
    import subprocess
    proc = subprocess.run([image], capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout


class Failure(Exception):
    pass


def check(name, cond, detail=""):
    if cond:
        print(f"PASS  {name}")
        return True
    print(f"FAIL  {name}  {detail}")
    return False


# ── the join, read directly ───────────────────────────────────────────────

def parse_defs(source):
    """`{name: [FunctionDef]}` for the module, which is what `_name_defs` is."""
    stmts = B.parse_module(source)
    out = {}
    for st in stmts:
        if isinstance(st, F.FunctionDef):
            out.setdefault(st.name, []).append(st)
    return out


def frame_struct(name="R"):
    stmts = B.parse_module(f"struct {name}:\n    var a: Int\n    var b: Int\n")
    return [s for s in stmts if isinstance(s, F.StructDef)][0]


def test_the_join_answers_only_what_agrees():
    """`_returns_frame_by_name` over the three shapes, with no build at all."""
    R = frame_struct()
    results = []

    # One definition, frame-returning: the name answers.
    defs = parse_defs("def f(self: R) -> Int:\n    return self\n")
    returns_frame = {B._fn_key(defs["f"][0]): R}
    view, conflicts = B._returns_frame_by_name(defs, returns_frame)
    results.append(check("join_answers_a_single_definition",
                         view.get("f") is R and not conflicts))

    # Two definitions, both frame-returning of the SAME struct: still answers.
    # The identity comparison, not `==`, is what makes this true, and the case
    # that needs it is two DIFFERENT StructDefs of one name.
    defs = parse_defs("def f(self: R) -> Int:\n    return self\n"
                      "def f[K: Copyable](self: R) -> Int:\n    return self\n")
    returns_frame = {B._fn_key(d): R for d in defs["f"]}
    view, conflicts = B._returns_frame_by_name(defs, returns_frame)
    results.append(check("join_answers_overloads_that_agree",
                         view.get("f") is R and not conflicts))

    # Neither definition returns a frame: absent, and NOT a conflict — that is
    # today's behaviour for every ordinary overloaded pair and must not change.
    defs = parse_defs("def f(self: R) -> Int:\n    return self.a\n"
                      "def f[K: Copyable](self: R) -> Int:\n    return self.a\n")
    returns_frame = {}
    view, conflicts = B._returns_frame_by_name(defs, returns_frame)
    results.append(check("join_is_quiet_when_nothing_returns_a_frame",
                         "f" not in view and not conflicts))

    # One returns a frame, the other does not: absent AND reported. The second
    # half is what the build refuses on.
    defs = parse_defs("def f(self: R) -> Int:\n    return self\n"
                      "def f[K: Copyable](self: R) -> Int:\n    return self.a\n")
    returns_frame = {B._fn_key(defs["f"][0]): R}
    view, conflicts = B._returns_frame_by_name(defs, returns_frame)
    rows = conflicts.get("f") or []
    results.append(check("join_reports_a_disagreeing_overload",
                         "f" not in view and len(rows) == 2,
                         f"view={sorted(view)} rows={rows}"))
    results.append(check(
        "the_report_names_both_definitions",
        [spelling for spelling, _answer in rows] == ["f", "f[K]"],
        f"rows={rows}"))
    results.append(check(
        "the_report_says_which_returns_what",
        [answer for _s, answer in rows]
        == ["a frame address of R", "an ordinary value"],
        f"rows={rows}"))

    # Two definitions returning frames of DIFFERENT layouts: the caller's block
    # would be sized for one of them, so this is a disagreement too — and it is
    # the one a `==` comparison would have missed if the two structs had the
    # same field names.
    R2 = frame_struct()
    R2.name = "R"
    defs = parse_defs("def f(self: R) -> Int:\n    return self\n"
                      "def f[K: Copyable](self: R) -> Int:\n    return self\n")
    returns_frame = {B._fn_key(defs["f"][0]): R, B._fn_key(defs["f"][1]): R2}
    view, conflicts = B._returns_frame_by_name(defs, returns_frame)
    results.append(check("two_layouts_of_one_name_are_a_disagreement",
                         "f" not in view and len(conflicts.get("f") or []) == 2,
                         f"view={sorted(view)} conflicts={conflicts}"))
    return all(results)


def test_the_refusal_message_says_what_is_wrong():
    rows = [("f", "a frame address of R"), ("f[K]", "an ordinary value")]
    message = M.frame_return_overloads_disagree_refusal("f", rows)
    results = [
        check("the_message_names_the_name", message.startswith("f is declared")),
        check("the_message_carries_both_answers",
              "a frame address of R" in message
              and "an ordinary value" in message),
        check("the_message_says_why_it_cannot_choose",
              "reserve a block" in message),
    ]
    return all(results)


def test_the_certificate_sees_content_not_sizes():
    """`_holder_state` must move when the tables move, and only then.

    A size comparison would miss a name traded for another and a candidate list
    replaced by an equal-length one, and either of those is a pass whose
    successor decides differently — which is the case the certificate exists to
    catch.
    """
    stmts = B.parse_module("struct R:\n    var a: Int\n    var b: Int\n")
    st = [s for s in stmts if isinstance(s, F.StructDef)][0]
    st2 = [s for s in B.parse_module(
        "struct S:\n    var a: Int\n    var b: Int\n") if isinstance(s, F.StructDef)][0]
    holders = {1: {"h"}, 2: set()}
    hstruct = {1: {"h": [st]}, 2: {}}
    returns_frame = {}
    base = B._holder_state(holders, hstruct, returns_frame)
    results = [check("the_base_state_is_a_snapshot", base == base)]

    grew = {1: {"h", "q"}, 2: set()}
    results.append(check("a_new_holder_moves_it",
                         B._holder_state(grew, hstruct, returns_frame) != base))

    # Same SIZES, different content: a candidate list replaced by another
    # struct's. A size-only comparison would call this unchanged.
    swapped = {1: {"h"}, 2: set()}
    swapped_h = {1: {"h": [st2]}, 2: {}}
    results.append(check(
        "an_equal_length_candidate_swap_moves_it",
        len(hstruct[1]["h"]) == len(swapped_h[1]["h"])
        and B._holder_state(swapped, swapped_h, returns_frame) != base))

    # One struct replaced by another of the same NAME (which is what a
    # re-parse would produce) must also move: identity, not equality.
    st.name = "R"
    st2.name = "R"
    same_named = {1: {"h"}, 2: set()}
    same_named_h = {1: {"h": [st2]}, 2: {}}
    results.append(check(
        "a_same_named_other_struct_moves_it",
        B._holder_state(same_named, same_named_h, returns_frame) != base))

    # The returned-frame table is part of the state, both directions.
    with_frame = {1: {"h"}, 2: set()}
    rf = {1: st}
    results.append(check("an_entered_frame_return_moves_it",
                         B._holder_state(with_frame, hstruct, rf) != base))
    return all(results)


def test_the_hang_shape_terminates(tmpdir):
    """The regression itself: the fifteen-line program, built, with a clock.

    Pre-fix this does not return. Post-fix it is a refusal naming both
    definitions — which is the outcome to insist on, because "it stopped
    hanging" could also have been "it built an image nobody checked".
    """
    t0 = time.time()
    rc, text, _out = build(OVERLOAD_DISAGREES, "overload_disagrees", tmpdir)
    secs = time.time() - t0
    results = [
        check("the_hang_shape_terminates", secs < BUILD_BUDGET_SECONDS,
              f"took {secs:.0f}s"),
        check("the_hang_shape_is_refused", rc != 0, f"rc={rc} out={text[:200]}"),
        check("the_refusal_names_the_overload",
              "declared more than once" in text and "give[K]" in text,
              f"out={text[:300]}"),
    ]
    return all(results)


def test_an_agreeing_overload_still_builds_and_runs(tmpdir):
    """The join must not cost a correct program its answer.

    An over-eager fix — "a name with two definitions has no answer" — passes the
    hang case and fails this one, so the pair belongs in one file.
    """
    rc, text, image = build(OVERLOAD_AGREES, "overload_agrees", tmpdir)
    if not check("an_agreeing_overload_builds", rc == 0, f"rc={rc} {text[:300]}"):
        return False
    if not os.path.exists(image):
        return check("the_agreeing_overload_wrote_an_image", False, image)
    status, _stdout = run(image)
    # 7 * 10 + 8 = 78: `s` is a frame of R copied into main's own block.
    return check("an_agreeing_overload_computes_the_right_answer",
                 status == 78, f"exit {status}, expected 78")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    tests = [
        ("the_join_answers_only_what_agrees", test_the_join_answers_only_what_agrees),
        ("the_refusal_message_says_what_is_wrong",
         test_the_refusal_message_says_what_is_wrong),
        ("the_certificate_sees_content_not_sizes",
         test_the_certificate_sees_content_not_sizes),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        tests += [
            ("the_hang_shape_terminates",
             lambda: test_the_hang_shape_terminates(tmpdir)),
            ("an_agreeing_overload_still_builds_and_runs",
             lambda: test_an_agreeing_overload_still_builds_and_runs(tmpdir)),
        ]
        failed = 0
        for name, fn in tests:
            print(f"── {name}")
            try:
                ok = fn()
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                print(f"FAIL  {name}  {type(e).__name__}: {e}")
                ok = False
            if not ok:
                failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())