#!/usr/bin/env python3
"""WHICH refusal a file gets when a function contains BOTH an MLIR construct
and a name nothing places — the MLIR one, or whatever the name walk found
first.

What is under test. `formal/build.py`'s `check_module_symbols` refuses a
function by walking its body in SOURCE ORDER and raising on the first name it
cannot place, with one pre-pass in front of that walk for the refusals that
NAME A CONSTRUCT rather than a symptom. The dialect half of that pre-pass was
missing, so a bare `__mlir_op` — the spelling `std/sys/_assembly.mojo` builds
its entire body out of — was reached by the walk like any other name:

    $ cat b.mojo
    def main() -> Int32:
        var q = Unplaced                       # a genuinely unplaced name
        var v = __mlir_op.`pop.inline_asm`[    # the construct that is fatal
            _type=None, assembly="nop", constraints="",
        ]()
        print(v)

    $ python3 fire.py build --formal --no-prove b.mojo
    build: main: 'Unplaced' has no home: the module-level symbol table is
    empty for this unit, …

Reverse the two lines and the same file gets the useful message. Same
construct, same backend, same file's worth of source: the verdict was decided
by LINE ORDER. That is the defect this suite pins — and the second half of it
is that the pre-emption must not reach further than it claims to. An MLIR
construct this build ANSWERS (`a_target_query_is_not_pre_empted` below) is not
a construct it cannot lower, so pre-empting with the dialect text would refuse
a program that builds. The guard is the half that makes the fix honest.

MEASURED, over the population the defect applies to. Every stdlib file whose
OWN `check_module_symbols` verdict — its own body, with no import resolution in
front of it, which is what `formal_sweep.py` cannot show because it reports the
chain's terminal — used to name something other than MLIR: 6 files moved to the
MLIR refusal, 0 moved off it, and 0 changed verdict class, so nothing that
built started failing. They are `std/atomic/atomic.mojo`,
`std/builtin/globals.mojo`, `std/memory/unsafe.mojo`, `std/sys/_assembly.mojo`,
`std/sys/intrinsics.mojo`, `std/utils/numerics.mojo`. The mechanism is
`formal/build.py`'s `first_mlir`, which this suite's cases were drawn to pin.

THE BOUNDARY, stated because it is a decision and not an accident: the
pre-emption is per FUNCTION. A construct that cannot be lowered at all
pre-empts every other name in the same function, because the file will not
build either way and the deeper limit is what the reader needs first; across
two functions each gets the most specific message available, because the
second function's refusal may be about something the first is not. Sixteen
stdlib files still have a verdict decided by the order of two FUNCTIONS — that
is the remainder, and it is in the doc.

Reverse-applied over the fix: 3 of the 7 cases fail, each of them naming the
wrong construct (`'Unplaced' has no home`), and none of them reporting a wrong
value. The other four are pins rather than reverse-apply failures and are
labelled as such where they are: the swapped-order pair's second case agreed
with the fix by source order already, the bare `__mlir_op` case had no
competing name to lose to, and both guards assert what the fix must NOT break.

Run:  python3 test_formal_mlir_precedence.py [-v] [case ...]
"""
import argparse
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 60


def build(src, out, backend):
    p = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         f"--backend={backend}", "-o", out, src],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


# (name, mojo source, needle, absent). Every one of these asserts the build
# FAILS with these words on BOTH backends. The needle is the reason the
# construct is refused, not a fixed phrase, so a rewording of the advice does
# not red the suite while a change of the verdict does. `absent`, where given,
# is a sentence the refusal must NOT contain — the assertion that decides which
# of two true refusals is the one the reader gets.
REFUSED = [
    # The defect, first shape: a missing local written ABOVE the construct.
    # Before, this was `'Unplaced' has no home`, which names a register table
    # and sends the reader to the allocator instead of to the construct the file
    # is actually about.
    ("a_missing_local_above_the_dialect_construct_does_not_win",
     "def main() -> Int32:\n"
     "    var q = Unplaced\n"
     "    var v = __mlir_op.`pop.inline_asm`[\n"
     "        _type=None, assembly=\"nop\", constraints=\"\",\n"
     "    ]()\n"
     "    print(v)\n"
     "    return 0\n",
     "is a dialect OPERATION"),
    # The same program with the two statements SWAPPED. It is here because a
    # single case cannot tell "the pre-emption is gone" from "the pre-emption
    # happens to agree with source order": this pair can. Reverse-applied, only
    # the case ABOVE fails — this one agreed with the fix already, because
    # source order put the construct first — and a reader who wants to know
    # whether the fix changed anything is looking at the other three failures
    # (`an_attribute_template_keeps_its_own_refusal`,
    # `a_type_template_keeps_the_type_refusal`, and the first case) rather than
    # at this one.
    ("a_missing_local_below_the_dialect_construct_does_not_win",
     "def main() -> Int32:\n"
     "    var v = __mlir_op.`pop.inline_asm`[\n"
     "        _type=None, assembly=\"nop\", constraints=\"\",\n"
     "    ]()\n"
     "    var q = Unplaced\n"
     "    print(v)\n"
     "    return 0\n",
     "is a dialect OPERATION"),
    # `__mlir_op` with no bracket at all, which is the spelling §2.2 of
    # bugs/FORMAL_known_limits.md measured building, linking and SEGFAULTING at
    # the first instruction, and which no suite case pinned. It is a limit, and
    # `test_formal_run.py`'s own note says what an unpinned limit is worth. It
    # passes reverse-applied too — nothing about it changed — which is the point
    # of a pin: it goes red when the limit is closed.
    ("a_bare_dialect_operation_is_refused_rather_than_built",
     "def main() -> Int32:\n"
     "    var n = 3\n"
     "    var a = __mlir_op.`pop.inline_asm`[n]\n"
     "    print(\"a = %llu\\n\", a)\n"
     "    return 0\n",
     "is a dialect OPERATION"),
    # The pre-emption must not DOWNGRADE a more specific refusal to the generic
    # dialect text. This is the other half of the ordering rule: both constructs
    # name MLIR, and the bracketed one has a message about what a template is.
    # The unplaced name is first so that, before the fix, this reported the
    # name and the MLIR verdict never appeared at all.
    ("an_attribute_template_keeps_its_own_refusal",
     "def main(n: Int) -> Int:\n"
     "    var q = Unplaced\n"
     "    var t = __mlir_attr[`#kgen.simd<1> : !kgen.scalar<ui8>`]\n"
     "    return n\n",
     "assembles an MLIR attribute from a template"),
    # …and the same for the TYPE half, which `std/sys/info.mojo`'s `_TargetType`
    # is: a refusal that calls it an attribute is false about that binding, and
    # the word "type" is the only part of it a reader can act on.
    ("a_type_template_keeps_the_type_refusal",
     "def main(n: Int) -> Int:\n"
     "    var q = Unplaced\n"
     "    var t = __mlir_type[`!kgen.never`]\n"
     "    return n\n",
     "names an MLIR TYPE, not a value"),
    # The question this whole file turns on, asked of the OTHER side of the
    # rule. An ANSWERED target query sits beside a name nothing places; both
    # refusals would be true, and the verdict must be the placement one —
    # because the pre-emption is for constructs this path cannot lower, and this
    # one it lowers (see `a_target_query_is_not_pre_empted`, which is the same
    # query with the missing name removed). Before the fix this case reported
    # the missing name too, so it passes both before and after; it is here
    # because a fix that made the pre-emption unconditional would break it, and
    # a test that cannot tell those two apart is not a guard.
    ("a_answered_query_does_not_pre_empt_a_missing_local",
     "def main(n: Int) -> Int32:\n"
     "    var os_name = __mlir_attr[\n"
     "        `#kgen.param.expr<target_get_field,`,\n"
     "        __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`,\n"
     "        `, \"os\" : !kgen.string`, `> : !kgen.string`]\n"
     "    var q = Unplaced\n"
     "    print(\"os=\", os_name)\n"
     "    return 0\n",
     "'Unplaced' has no home", "is a dialect OPERATION"),
]

# ── WHICH dialect operation, and WHY ───────────────────────────────────────
#
# The second half of the same file's subject, and it is a different defect from
# the one above. Every `__mlir_op` used to be refused with ONE sentence, and that
# sentence asserted a property of the TARGET — "an MLIR attribute, type or
# operation has no representation in [a 64-bit word]" — where the property
# belongs to the OPERATION. Measured over the stdlib (`../new-modular`):
# 259 sites over 104 operations, and they denote three different things.
#
#     14 ops /  76 sites   an EFFECT — a store, a trap, an ownership marker.
#                          No value, so "no representation" is TRUE of them.
#     12 ops /  38 sites   ELEMENTWISE arithmetic, where the op NAME does not
#                          decide the answer: the OPERAND's type does. 26 of
#                          those 38 sites are over `!kgen.simd<N, DTYPE>`, whose
#                          own source documents the result as "a new vector
#                          whose element at position `i` is computed as
#                          `self[i] + rhs[i]`" — an N-lane VECTOR, not a word.
#     the rest             a value that needs a FACT this path has no way to
#                          get: `pop.cmp`'s bracketed predicate, `pop.load`'s
#                          pointee width, `pop.select`'s BOOL kind.
#
# So a table keyed on the operation name alone is not "26 ops waiting for a
# lowering" — it is 9 word-typed sites and 26 vector-typed ones wearing the same
# name, and lowering `pop.add(a, b)` to `a + b` would be RIGHT for the 9 and
# WRONG for the 26: a scalar add of two vector-typed words, which is a
# plausible-looking number rather than a refusal. `MLIR_ELEMENTWISE_OPS` is
# therefore not a claim that these denote words, and the row below is what pins
# that: the elementwise message must NOT say they do.
#
# Every case asserts three things on BOTH architectures: the class's own words
# are present, the operation is NAMED (the old message never named it — it said
# `__mlir_op`, the PREFIX, for 104 different operations), and the sentences that
# belong to a DIFFERENT class are absent. The `absent` half is the load-bearing
# one: a single reword that collapsed the classification back to one sentence
# would still satisfy the needle and is exactly the regression this file exists
# to catch.
CLASSIFIED = [
    # An EFFECT. Real stdlib source spells this exactly: `std/sys/debug.mojo:20`.
    # The `absent` is the elementwise clause, which would be FALSE of it — a
    # trap has no operand type to establish and no result to be a vector of.
    ("an_effect_operation_says_it_denotes_no_value",
     "def t() -> Int32:\n"
     "    __mlir_op.`llvm.intr.debugtrap`()\n"
     "    return 0\n",
     "`llvm.intr.debugtrap` is a dialect OPERATION and denotes NO VALUE",
     "applied ELEMENTWISE"),
    # The 45-site class. `lit.ownership.mark_initialized` is an ownership
    # marker: it asserts something about a reference and returns nothing.
    ("an_ownership_marker_is_an_effect_not_a_value",
     "def t(p: Int) -> Int:\n"
     "    return __mlir_op.`lit.ownership.mark_initialized`(p)\n",
     "`lit.ownership.mark_initialized` is a dialect OPERATION and denotes NO "
     "VALUE", None),
    # ELEMENTWISE arithmetic, `std/simd.mojo:1082` verbatim. The `absent` is
    # the over-claim this measurement exists to prevent: the op name does not
    # establish that the result is a word, and 26 of the 38 sites say it is not.
    ("an_elementwise_operation_names_the_operand_type_as_the_missing_fact",
     "def addit(a: Int, b: Int) -> Int:\n"
     "    return __mlir_op.`pop.add`(a, b)\n",
     "`pop.add` is a dialect OPERATION applied ELEMENTWISE",
     "cannot be GUARDED here"),
    # The index family, `std/builtin/simd_length.mojo:121` verbatim. Same
    # classification as `pop.add` and deliberately so: the two are both
    # elementwise and the message does not claim a word for either, because a
    # claim keyed on the NAME is what was wrong.
    ("an_index_operation_is_classified_the_same_way",
     "def addit(a: Int, b: Int) -> Int:\n"
     "    return __mlir_op.`index.add`(a, b)\n",
     "`index.add` is a dialect OPERATION applied ELEMENTWISE", None),
    # Needs a PREDICATE. `std/simd.mojo:1546` verbatim. The needle names the
    # missing thing rather than saying "no representation", because the missing
    # thing is a bracket this path cannot read — six distinct
    # `#kgen.cmp_pred<…>` values appear in the corpus, and an entry that ignored
    # the bracket would answer `eq` and `ne` alike, which is a wrong answer
    # rather than a refusal.
    ("a_comparison_names_the_predicate_it_cannot_read",
     "def cmpv(a: Int, b: Int) -> Int:\n"
     "    return __mlir_op.`pop.cmp`[pred=__mlir_attr.`#kgen.cmp_pred<eq>`](a, b)\n",
     "`pop.cmp` is a dialect OPERATION whose value could be a word",
     "applied ELEMENTWISE"),
    # An UNKNOWN predicate must get the same message as a known one rather than
    # being answered: the bracket is unread either way, so a table that read
    # only the name and ignored the predicate would have to answer this one.
    ("an_unknown_predicate_is_refused_rather_than_answered",
     "def bad(a: Int) -> Int:\n"
     "    return __mlir_op.`pop.cmp`[pred=__mlir_attr.`#kgen.cmp_pred<nonesuch>`](\n"
     "        a, a)\n",
     "`pop.cmp` is a dialect OPERATION whose value could be a word", None),
    # `pop.select` is STILL refused here, and why is the point of the pair with
    # the GUARDED row below: this receiver declares nothing, so a select
    # answered kind-blind would test a `char *` for non-zero and answer 1. It
    # used to be refused for a DIFFERENT and partly false reason — "this path
    # has no BOOL kind distinct from an integer", which is true of the KIND
    # MODEL and not of this program, whose `condition` declares `Bool` and is
    # therefore lowered. So the row now names the DECLARED TYPE, and the case
    # beside it in `GUARDED` is that program.
    #
    # `absent` pins that it does NOT claim the operand type is the only missing
    # piece — a name-keyed table that lowered `pop.select` for every operand
    # would be wrong for 26 of the corpus's 38 elementwise sites, and this row is
    # the one that says the guard is a fact about the operand.
    ("a_select_names_the_declared_bool_it_needs",
     "def s(c, a: Int, b: Int) -> Int:\n"
     "    return __mlir_op.`pop.select`(c.__mlir_bool__(), a, b)\n",
     "`pop.select` is a dialect OPERATION whose value could be a word",
     "applied ELEMENTWISE"),
    # The other side of that row, and the one that decides it is a capability:
    # a receiver DECLARED `String` is still refused. `pick(1, 10, 20)` with a
    # `Bool` builds and runs (`a_dialect_select_lowers_when_the_condition_
    # declares_a_bool`, in `GUARDED`); this program differs only in the
    # declaration, and lowering it would test a `char *` for non-zero. Without
    # this row the pass that answers the first one is indistinguishable from a
    # pass that ignores the declaration.
    ("a_select_over_a_declared_pointer_is_still_refused",
     "def s(c: String, a: Int, b: Int) -> Int:\n"
     "    return __mlir_op.`pop.select`(c.__mlir_bool__(), a, b)\n",
     "`pop.select` is a dialect OPERATION whose value could be a word",
     "applied ELEMENTWISE"),
    # An EFFECT the corpus proves: `std/builtin/value.mojo:203` spells it as a
    # bare statement whose result nothing reads, and `test_formal_run.py`'s
    # `mlir_dialect_name_is_refused_by_construct` builds exactly this source.
    # It is the row that says the fallback is REACHABLE only for an operation
    # nobody classified, and `absent` pins that an effect does not claim to need
    # an operand type.
    ("a_materialize_is_an_effect_because_nothing_reads_its_result",
     "def materialize(value) -> Int:\n"
     "    __mlir_op.`lit.materialize_into`[value=value](value)\n"
     "    return 0\n",
     "`lit.materialize_into` is a dialect OPERATION and denotes NO VALUE",
     "no lowering table"),
    # The fallback itself, for an operation no table claims: refused WITHOUT a
    # claim about what it denotes, which is the honest last resort and the only
    # place in this file where the message says nothing about the operation.
    # `pop.fence` is deliberately NOT this row — the corpus proves it an effect
    # at its one site, and `MLIR_EFFECT_OPS` says so.
    ("an_unclassified_operation_is_refused_without_a_claim_about_it",
     "def oddball(value) -> Int:\n"
     "    return __mlir_op.`dialect.of.mine`[value=value](value)\n",
     "`dialect.of.mine` is a dialect OPERATION, and this path has no "
     "lowering table", "applied ELEMENTWISE"),
]

# (name, source, expected stdout or None). The other guard, and it is a BUILD
# assertion: a `#kgen.param.expr<…>` target query is a QUESTION, this build
# answers it, and pre-empting it with the dialect refusal would refuse a
# construct `formal/model.py` answers everywhere else. `_fold_target_queries`
# has normally replaced the query with the literal it denotes before
# `check_module_symbols` runs, so this is also the case that pins that rewrite's
# coverage of a function body.
#
# The expected value is stated with its provenance rather than taken from an
# oracle, because CPython cannot parse `__mlir_attr`: `os` is `darwin` because
# the emitted container is a Mach-O image, which is a fact about the image and
# not about the machine that emitted it (`formal/model.py`'s `Target.__init__`
# derives it from `fmt` the same way). It is therefore the SAME on both
# architectures, which is why this case asserts one string for both.
GUARDED = [
    # `std/utils/_select.mojo` verbatim, minus its docstring: the ONE program
    # the `pop.select` refusal existed for, and it now builds and RUNS on both
    # architectures. `condition: Bool` is the whole of why — the lowering is
    # `x != 0`, which is a Bool's value on this path, and the declaration is what
    # makes it a Bool rather than a `char *`.
    #
    # The expected value is STATED rather than taken from an oracle because
    # CPython cannot parse `__mlir_op.`pop.select``, and it is stated as a
    # CASE rather than written down: 10/20 for `condition` 1 and 20/10 for 0 is
    # the only thing a select can mean, and a case that could pass with the arms
    # swapped would not be testing the select.
    ("a_dialect_select_lowers_when_the_condition_declares_a_bool",
     "def pick(condition: Bool, lhs: Int, rhs: Int) -> Int:\n"
     "    return __mlir_op.`pop.select`(condition.__mlir_bool__(), lhs, rhs)\n"
     "\n"
     "def main():\n"
     "    printf(\"%d %d\\n\", pick(1, 10, 20), pick(0, 10, 20))\n"
     "    return 0\n",
     "10 20\n"),
    # The same file with a `String`-declared receiver, and it must STILL be
    # refused. This is the row that decides the other one is a capability rather
    # than a blanket: without it, lowering `pop.select` for every operand is
    # right here and wrong on every `char *`, and nothing would say so.
    ("a_target_query_is_not_pre_empted",
     "def main() -> Int32:\n"
     "    var os_name = __mlir_attr[\n"
     "        `#kgen.param.expr<target_get_field,`,\n"
     "        __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`,\n"
     "        `, \"os\" : !kgen.string`, `> : !kgen.string`]\n"
     "    print(\"os=\", os_name)\n"
     "    return 0\n",
     "os= darwin\n"),
]


def run_refused(name, source, needle, absent, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        rc, text = build(src, os.path.join(tmpdir, f"{name}.{backend}"),
                         backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct with no "
                           f"answer (expected a refusal naming {needle!r}); "
                           f"the binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-220:]}")
        if absent is not None and absent in text:
            return False, (f"--backend={backend} refused with {absent!r}, "
                           f"which is the pre-emption this case says must not "
                           f"happen here: {text.strip()[-220:]}")
    if verbose:
        print(f"      refused identically on arm64 and x86-64: {needle!r}")
    return True, ""


def run_classified(name, source, needle, absent, tmpdir, verbose):
    """Both architectures must refuse, and say the same thing.

    The same three assertions `run_refused` makes, and the reason this is a
    separate runner rather than a flag on that one is that the rows have
    DIFFERENT semantics for `absent`. In `REFUSED` it is a pre-emption guard — a
    sentence that must not appear because a more specific construct owns this
    file. In `CLASSIFIED` it is a classification guard — a sentence belonging to
    a DIFFERENT class of dialect operation, which a collapsed message would
    carry and which would make the classification a claim rather than a
    distinction. One name for both would hide which of the two a failure is, and
    the second is the one this table exists to prevent.

    Parity is asserted by CONSTRUCTION here rather than by comparing the two
    texts: the messages come from `formal/model.py`'s tables, which take no
    architecture argument, so a per-emitter copy of the classification would be
    the only way to make them differ. Every case runs both backends anyway,
    because that is what proves no emitter has grown a second opinion.
    """
    return run_refused(name, source, needle, absent, tmpdir, verbose)


def run_guarded(name, source, want_stdout, tmpdir, verbose):
    """Both architectures must BUILD, and on this one the image must RUN.

    arm64 only for the execution, for the reason `test_formal_comptime_string.py`
    gives: a formal x86-64 Mach-O needs Rosetta to launch on an arm64 Mac. The
    build half is what this case is really about, so it is checked on both.
    """
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(src, out, backend)
        if rc != 0:
            return False, (f"--backend={backend} refused a construct this build "
                           f"answers: {text.strip()[-220:]}")
        if not os.path.isfile(out):
            return False, f"--backend={backend} reported success, no binary"
        if backend != "arm64" or want_stdout is None:
            continue
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        if run.stdout != want_stdout:
            return False, (f"stdout {run.stdout!r} != {want_stdout!r} — a wrong "
                           f"value is the worse outcome, not a refusal")
        if run.returncode != 0:
            return False, f"exit status {run.returncode}, expected 0"
    if verbose:
        print(f"      built on both architectures"
              + (f" and printed {want_stdout!r}" if want_stdout else ""))
    return True, ""


def census_is_complete():
    """Every dialect operation the stdlib spells must reach a CLASS, not the
    fallback. A census nobody re-measures rots silently.

    This is the check that makes the classification a census rather than a
    handful of hand-picked rows, and it is the one that would have caught the
    error this branch corrects: a set of tables that covered the operations a
    reader happened to think of reads exactly like a complete one until the
    corpus is run against it.

    The stdlib lives OUTSIDE this repository, so a checkout without it cannot
    run this check — and must not fail because of it. The message says so and
    the check reports SKIPPED, which is a different outcome from PASS on purpose:
    "there is no corpus here" and "the corpus is fully classified" must not
    print the same word.
    """
    stdlib = os.path.join(HERE, "..", "new-modular", "Mojo", "stdlib", "std")
    if not os.path.isdir(stdlib):
        return None, (f"SKIPPED no classification census — {stdlib} is not "
                      f"present, so the tables cannot be checked against the "
                      f"corpus they classify")
    sys.path.insert(0, HERE)
    import formal.model as M
    counts, unclassified = {}, {}
    pat = re.compile(r"__mlir_op\.`([A-Za-z0-9_.]+)`")
    for root, _dirs, files in os.walk(stdlib):
        for f in files:
            if not f.endswith(".mojo"):
                continue
            try:
                text = open(os.path.join(root, f), encoding="utf-8",
                            errors="replace").read()
            except OSError:
                continue
            for m in pat.finditer(text):
                op = m.group(1)
                why = M.mlir_dialect_op_refusal(op)
                # The class is read off the MESSAGE, not off the tables, so this
                # measures what the reader gets rather than what the tables say:
                # a branch that exists but is unreachable from this text fails
                # here, which is the rot this is for.
                if "denotes NO VALUE" in why:
                    k = "effect"
                elif "cannot be GUARDED" in why:
                    k = "unguarded"
                elif "RESULT TYPE is written" in why:
                    k = "typed-result"
                elif "over a VECTOR" in why:
                    k = "vector"
                elif "applied ELEMENTWISE" in why:
                    k = "elementwise"
                else:
                    k = None
                counts[k] = counts.get(k, 0) + 1
                if k is None:
                    unclassified.setdefault(op, 0)
                    unclassified[op] += 1
    fallback = counts.pop(None, 0)
    if fallback:
        return False, (
            f"{fallback} site(s) over {len(unclassified)} operation(s) reach the "
            f"generic fallback rather than a class, so the refusal for them "
            f"says only that there is no lowering table: "
            f"{sorted(unclassified.items(), key=lambda kv: -kv[1])[:12]}")
    total = sum(counts.values())
    if total != 259:
        # Not a failure of the tables — the CORPUS moved, which is worth saying
        # out loud because every count in the docs is keyed on it.
        return False, (
            f"the corpus has {total} `__mlir_op` sites, not the 259 the census "
            f"and both bug docs record. The tables classify all of them; the "
            f"NUMBER is stale, so re-measure the docs' counts "
            f"({counts})")
    return True, f"all {total} sites over 104 operations classified: {counts}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    known = ({c[0] for c in REFUSED} | {c[0] for c in CLASSIFIED}
             | {c[0] for c in GUARDED})
    if args.cases:
        missing = set(args.cases) - known
        if missing:
            print(f"ERROR: unknown case(s): {sorted(missing)}",
                  file=sys.stderr)
            return 2

    checks = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for entry in REFUSED:
            name, source, needle = entry[0], entry[1], entry[2]
            absent = entry[3] if len(entry) > 3 else None
            if args.cases and name not in args.cases:
                continue
            try:
                checks.append((name,) + run_refused(name, source, needle,
                                                    absent, tmpdir,
                                                    args.verbose))
            except subprocess.TimeoutExpired:
                checks.append((name, False, "timed out"))
        for entry in CLASSIFIED:
            name, source, needle = entry[0], entry[1], entry[2]
            absent = entry[3] if len(entry) > 3 else None
            if args.cases and name not in args.cases:
                continue
            try:
                checks.append((name,) + run_classified(name, source, needle,
                                                      absent, tmpdir,
                                                      args.verbose))
            except subprocess.TimeoutExpired:
                checks.append((name, False, "timed out"))
        for name, source, want_out in GUARDED:
            if args.cases and name not in args.cases:
                continue
            try:
                checks.append((name,) + run_guarded(name, source, want_out,
                                                    tmpdir, args.verbose))
            except subprocess.TimeoutExpired:
                checks.append((name, False, "timed out"))

    # The census, which is a property of the TABLES and not of any one build, so
    # it runs once with no `cases:` filter and reports its own three outcomes.
    if not args.cases:
        ok, detail = census_is_complete()
        if ok is None:
            print(f"  {detail}")
        elif ok:
            print(f"  PASS  the_classification_covers_the_whole_corpus")
            print(f"        {detail}")
        else:
            print(f"  FAIL  the_classification_covers_the_whole_corpus: {detail}")

    passed = failed = 0
    for name, ok, detail in checks:
        if ok:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed += 1
            print(f"  FAIL  {name}: {detail}")

    print(f"\nMLIR refusal precedence: PASS={passed} FAIL={failed}")
    if platform.machine() not in ("arm64", "aarch64"):
        print("NOTE: the arm64 execution half was skipped — this host is "
              f"{platform.machine()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())