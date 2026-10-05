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


# ── the CONTAINER twin: a blob that does not outlive its frame ─────────────
#
# `returns_frame` above is the machinery that makes a returned STRUCT sound: the
# caller reserves a block in its OWN scratch and passes its address as a hidden
# trailing argument, and the callee copies into it
# (`model.struct_returned_frame_sites`, `returned_frame_convention_refusal`).
# A CONTAINER had no such copy, because its words are laid out in the frame by
# `_blob_est` — so `return xs` handed the caller an address into memory that dies
# with the call. It has one now (`model.container_returned_blob_sites`: the
# CALLER reserves the block and copies the blob into it immediately after the
# call), and this is the program that used to be the measurement of the wrong
# answer the copy removes: `arm64` read `7 8 9` after `litter(7)` — that
# function's own scratch — and `x86_64` read `8 9 33`, a mix of the two frames,
# for the same source, while CPython answers `11 22 33` in both.
CONTAINER_ESCAPE = """\
def lit() -> List[Int]:
    return [11, 22, 33]


def litter(n) -> Int:
    var junk = []
    junk.append(n)
    junk.append(n + 1)
    junk.append(n + 2)
    return len(junk)


def main(n) -> Int:
    var p = lit()
    printf("right after: %d %d %d\\n", p[0], p[1], p[2])
    var k = litter(7)
    printf("after: %d %d %d\\n", p[0], p[1], p[2])
    return 0
"""

# The CONTROL, and it is why the refusal is at the READ: the same function read
# before this one calls anything else is correct, and this tree has a dozen of
# those on purpose — `formal/hostmods/struct.mojo`'s `unpack_from` is one and its
# docstring records the measurement ("a list built here is in this frame, which is
# correct for the corpus's immediate `[0]`"), and
# `formal/x86_64_decode.py` reads `struct.unpack_from("<i", code, at)[0]` that
# way. A refusal at the RETURN would take that module out, for a use its own
# author measured as sound.
CONTAINER_IMMEDIATE = """\
def lit() -> List[Int]:
    return [11, 22, 33]


def main(n) -> Int:
    var p = lit()
    printf("%d %d %d\\n", p[0], p[1], p[2])
    return 0
"""


# The two shapes the copy CANNOT own, and they are the boundary rather than an
# oversight.  A NESTED blob puts an address into the block, and the address is
# still into the callee's frame after the copy; a callee that does not return on
# every path leaves whatever was in the return register, and the copy would read
# from it.  Both keep the refusal, and both say the same sentence the copy's own
# documentation points at.
CONTAINER_NOT_OWNED_NESTED = """\
def nested(n) -> List[List[Int]]:
    var outer = []
    var inner = [n, n + 1]
    outer.append(inner)
    return outer


def litter(n) -> Int:
    var junk = []
    junk.append(n)
    return len(junk)


def main(n) -> Int:
    var o = nested(3)
    printf("right: %d %d\\n", o[0][0], o[0][1])
    var k = litter(7)
    printf("after: %d %d\\n", o[0][0], o[0][1])
    return 0
"""

CONTAINER_NOT_OWNED_MIXED_RETURN = """\
def maybe(n):
    if n > 0:
        return [11, 22]
    return 0


def litter(n) -> Int:
    var junk = []
    junk.append(n)
    return len(junk)


def main(n) -> Int:
    var p = maybe(1)
    printf("right: %d\\n", p[0])
    var k = litter(7)
    printf("after: %d\\n", p[0])
    return 0
"""


# ── the CONTAINER table, asked directly, with no build at all ──
#
# `model.returned_container_blob_bytes` decides WHERE a caller reads its copy
# from, so its interesting rows are ones an image cannot show: the shapes it
# declines are invisible in a build because the refusal that replaces them names
# something else. Each row is `(name, source, {callee: bytes}, {callee: why})`
# — the accepted sizes, and the names that must be ABSENT, because "absent" is
# the assertion a widening of the whitelist would break first.
CONTAINER_SIZE_ROWS = [
    # The count word plus three elements, and the over-estimate is visible here:
    # `n` is an unannotated PARAMETER, which `_plain_word_names` accepts, so the
    # literal is accepted and its size is the literal's own.
    ("a_literal_of_words_is_sized",
     "def f() -> List[Int]:\n    return [11, 22, 33]\n",
     {"f": 32}, {}),
    # A blob BUILT BY APPENDS: the capacity term is the append SITES (two here),
    # because `_blob_est`'s reservation has to have room for them and the count
    # word is one word on top. `8 * (1 + 2)`.
    ("a_blob_built_by_appends_is_sized",
     "def f(n) -> List[Int]:\n"
     "    var xs = []\n"
     "    xs.append(n)\n"
     "    xs.append(n + 1)\n"
     "    return xs\n",
     {"f": 24}, {}),
    # `return g()` takes g's size, and the fixpoint has to reach it: the callee
    # is declared AFTER the caller in this source on purpose, so a single pass
    # in source order would leave `f` unanswered.
    ("a_forwarded_return_takes_the_callees_size",
     "def f(n) -> List[Int]:\n    return g(n)\n"
     "def g(n) -> List[Int]:\n    return [n, n + 1]\n",
     {"f": 24, "g": 24}, {}),
    # A nested blob puts an ADDRESS into the block, and copying the block does
    # not move what the address names. This is the row that would fail first if
    # the element check were dropped.
    ("a_blob_of_blobs_is_not_sized",
     "def f(n) -> List[List[Int]]:\n    return [[n, n + 1]]\n", {}, {"f"}),
    # …and the same fact reached through an APPEND, where the literal has no
    # elements at all and the word arrives from the call.
    ("a_blob_given_an_appended_blob_is_not_sized",
     "def f(n) -> List[Int]:\n"
     "    var xs = []\n"
     "    xs.append([n, n + 1])\n"
     "    return xs\n",
     {}, {"f"}),
    # A LOCAL name is not a plain word: it can hold a frame address, and the
    # tables that would say so are published by a build pass this predicate does
    # not read. Refused, and the escape refusal still covers it.
    ("a_blob_of_a_local_is_not_sized",
     "def f(n) -> List[Int]:\n"
     "    var t = n + 1\n"
     "    return [t]\n",
     {}, {"f"}),
    # A parameter declared with a STRUCT annotation is a frame at entry, so it
    # is not a plain word — while `n: Int` is, and the two rows differ in one
    # token so the vocabulary `_plain_word_names` reads is the thing under test.
    ("a_blob_of_a_frame_annotated_parameter_is_not_sized",
     "def f(p: Point) -> List[Int]:\n    return [p.a]\n", {}, {"f"}),
    # A callee that does not return on every path leaves whatever the return
    # register held, and the copy reads `nbytes` from it.
    ("a_callee_that_does_not_always_return_is_not_sized",
     "def f(n):\n"
     "    if n > 0:\n"
     "        return [1, 2]\n"
     "    return 0\n",
     {}, {"f"}),
    # A concatenation sizes its result its own way (`_emit_list_concat` reserves
    # the sum of both sides), so answering for it here would be a second answer
    # to a question the emitters own.
    ("a_concatenated_return_is_not_sized",
     "def f(n) -> List[Int]:\n    return [1, 2] + [3]\n", {}, {"f"}),
    # A name that is a blob on one path and a word on another is two kinds of
    # value in one name.
    ("a_name_rebound_to_a_word_is_not_sized",
     "def f(n) -> List[Int]:\n"
     "    var xs = [1, 2]\n"
     "    xs = 7\n"
     "    return xs\n",
     {}, {"f"}),
]


def test_the_container_table_sizes_only_what_a_copy_can_own():
    """`returned_container_blob_bytes` over the accepted and declined shapes.

    Every row is a model call, so the declined shapes are visible here at all: in
    a build each of them ends at `returned_container_refusal`, whose text is
    about the READ and says nothing about why this particular callee has no size.
    """
    ok = True
    for name, source, want, absent in CONTAINER_SIZE_ROWS:
        absent = set(absent)
        defs = parse_defs(source)
        fns = [d for rows in defs.values() for d in rows]
        containers = M.functions_returning_containers(fns)
        sizes = M.returned_container_blob_bytes(
            fns, [f for f in fns if getattr(f, "name", None) in containers])
        ok &= check(name, {k: v for k, v in sizes.items() if k in want} == want,
                    f"sizes={sizes} want={want}")
        ok &= check(f"{name}__declines_what_it_must",
                    not (absent & set(sizes)),
                    f"{sorted(absent & set(sizes))} were sized")
    # The site table, and it is the OTHER half of the answer: every call of a
    # sized callee gets a block, at consecutive offsets, whether or not the call
    # binds a name — a call in an argument position dereferences the result
    # immediately and the block is what makes that read out of the caller's own
    # storage.
    defs = parse_defs(
        "def f(n) -> List[Int]:\n"
        "    return [n, n + 1]\n"
        "def g(n) -> List[Int]:\n    return [n]\n"
        "def main(n) -> Int:\n"
        "    var a = f(1)\n"
        "    printf(\"%d\", len(f(2)))\n"
        "    var b = g(3)\n"
        "    return len(a) + len(b)\n")
    fns = [d for rows in defs.values() for d in rows]
    containers = M.functions_returning_containers(fns)
    sizes = M.returned_container_blob_bytes(
        fns, [f for f in fns if getattr(f, "name", None) in containers])
    sites = M.container_returned_blob_sites(defs["main"][0], sizes)
    ok &= check("every_call_of_a_sized_callee_gets_a_block", len(sites) == 3,
                f"{len(sites)} sites for three calls")
    # Two calls of `f` (24 bytes each) and one of `g` (16), at consecutive
    # offsets in WALK order — the third block starts where the second ended,
    # which is what lets both backends reserve one region and start the blob
    # cursor above the lot.
    ok &= check("the_blocks_are_at_consecutive_offsets",
                sorted(v[1] for v in sites.values()) == [0, 24, 48]
                and sorted(v[0] for v in sites.values()) == [16, 24, 24],
                f"{sorted(sites.values())} for sizes={sizes}")
    # …and the refusal asks about exactly the sites the table fills, which is
    # what makes the two halves one decision rather than two that can disagree.
    # ONE escape and not two: `b` is bound by the last statement, so there is no
    # call after it to read past — which is the shape
    # `container_escape_sites` documents ("a caller that reads the value before
    # calling anything else has none either").
    escapes = M.container_escape_sites(defs["main"][0], containers)
    ok &= check("without_the_table_the_late_read_is_an_escape",
                len(escapes) == 1 and "`a`" in escapes[0][1],
                f"{len(escapes)} escapes: {escapes}")
    ok &= check("with_the_table_none_of_them_is",
                M.container_escape_sites(defs["main"][0], containers,
                                         set(sites)) == [],
                "a binding the emitters copy into the caller's own block was "
                "still reported as an escape")
    return ok


def test_a_container_read_after_a_call_is_OWNED(tmpdir):
    """The escape, on both architectures, and the immediate read beside it.

    This group was a build-and-REFUSE and is a build-and-RUN, and the measurement
    it pins is the reason that is the right direction: before the copy, `arm64`
    read `7 8 9` after `litter(7)` — that function's own scratch — and `x86-64`
    read `8 9 33`, a mix of the two frames, for the same source, while CPython
    answers `11 22 33` in both.  A program that builds, runs, exits 0 and prints
    a plausible answer is the one failure mode this backend exists to prevent, so
    the case is differential against CPython on both machines rather than a
    property read out of the model.

    `CONTAINER_ESCAPE` is the same source that produced the two wrong answers, so
    a copy that stopped being emitted would print them again and this row fails
    with the values in the message rather than with a build error.
    """
    ok = True
    for backend in ("arm64", "x86_64"):
        rc, text, image = build(CONTAINER_ESCAPE, "container_escape",
                                tmpdir, backend)
        if not check(f"[{backend}] a container read after another call builds",
                     rc == 0, f"rc={rc}; {text[:300]}"):
            ok = False
            continue
        status, stdout = run(image)
        ok &= check(
            f"[{backend}] …and answers CPython's answer in BOTH lines",
            status == 0
            and stdout.splitlines() == ["right after: 11 22 33",
                                        "after: 11 22 33"],
            f"exit {status}, stdout {stdout!r}, expected 11 22 33 twice")
    # The control, and it must still BUILD and answer: 11 22 33 on both machines.
    for backend in ("arm64", "x86_64"):
        rc, text, image = build(CONTAINER_IMMEDIATE, "container_immediate",
                                tmpdir, backend)
        if not check(f"[{backend}] a container read BEFORE any call builds",
                     rc == 0, f"rc={rc} {text[:300]}"):
            ok = False
            continue
        status, stdout = run(image)
        ok &= check(
            f"[{backend}] …and answers CPython's answer",
            status == 0 and stdout.split() == ["11", "22", "33"],
            f"exit {status}, stdout {stdout!r}, expected 11 22 33")
    return ok


def test_a_container_the_copy_cannot_OWN_is_still_refused(tmpdir):
    """The two shapes the copy declines, and they are the refusal still working.

    A returned blob of BLOBS puts an address into the block, and copying the
    block does not move what that address names; a callee that does not return on
    every path leaves whatever the return register held, and the copy would read
    `nbytes` from it.  Both keep `returned_container_refusal` word for word, so a
    reword that dropped the clause the taxonomy keys on fails here rather than
    quietly moving these two files into another row.
    """
    ok = True
    for label, src, tag in (("a nested blob", CONTAINER_NOT_OWNED_NESTED,
                             "container_not_owned_nested"),
                            ("a callee that does not return on every path",
                             CONTAINER_NOT_OWNED_MIXED_RETURN,
                             "container_not_owned_mixed")):
        for backend in ("arm64", "x86_64"):
            rc, text, _image = build(src, tag, tmpdir, backend)
            ok &= check(
                f"[{backend}] {label} is still refused", rc != 0,
                f"rc={rc}; the program built: {text[:200]}")
            ok &= check(
                f"[{backend}] {label} keeps the frame-reuse sentence",
                "does not outlive that function" in text
                and "read again" in text,
                f"{text[:400]}")
    return ok


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
            ("the_container_table_sizes_only_what_a_copy_can_own",
             test_the_container_table_sizes_only_what_a_copy_can_own),
            ("a_container_read_after_a_call_is_OWNED",
             lambda: test_a_container_read_after_a_call_is_OWNED(tmpdir)),
            ("a_container_the_copy_cannot_OWN_is_still_refused",
             lambda: test_a_container_the_copy_cannot_OWN_is_still_refused(
                 tmpdir)),
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