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

THE SECOND SUBJECT, added 2026-10-04: what the refusal says once the
operation's OPERAND type can be read. `bugs/FORMAL_mlir_dialect_refusal_is_
false_of_the_word_valued_ops.md` § Correction measured that the corpus's
arithmetic sites are scalar or vector depending on the OPERAND's declared type
and not on the operation's name — 9 word-typed, 26 over a `!kgen.simd<…>` — so a
table keyed on the name would have been right for nine and wrong for
twenty-six. `formal/build.py::_lower_dialect_arith` now reads the declaration
and rewrites the nine; `formal/model.py`'s `mlir_operand_clause` reports what it
read at the sites it declined, because "this path has no lowering table that
establishes the operand type" became untrue the moment the table could. The
`CLASSIFIED` rows added for it are the interesting half: each is a site where
the operand type IS established and the answer is still a refusal, and each says
which of the three things is missing — a VECTOR, an operation whose ordinary
spelling computes something else, or a `comptime` alias that states nothing.
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
    # An EFFECT that is STILL refused, as a statement of its own — which is the
    # shape `llvm.intr.debugtrap` used to be refused in, and the row that keeps
    # the class honest now that a trap lowers (see `a_trap_in_a_value_position`
    # and `EMITTED` below for that half).
    #
    # `lit.ownership.mark_destroyed` rather than a trap, and the choice is the
    # point: this operation is refused for a fact a trap does not have. It
    # asserts something about a REFERENCE — that the object it names is dead —
    # and this path tracks no ownership, so emitting the divergence for it would
    # be a different program wearing the same three instructions. The `absent`
    # is the elementwise clause, which would be FALSE of any effect: a marker
    # has no operand type to establish and no result to be a vector of.
    ("an_effect_operation_says_it_denotes_no_value",
     "def t(p: Int) -> Int:\n"
     "    __mlir_op.`lit.ownership.mark_destroyed`(p)\n"
     "    return 0\n",
     "`lit.ownership.mark_destroyed` is a dialect OPERATION and denotes NO "
     "VALUE",
     "applied ELEMENTWISE"),
    # The boundary of the trap lowering, and the row that says the lowering is a
    # CAPABILITY rather than a blanket: a trap whose value is READ is a value
    # position whatever its arguments are, so there is a result to represent and
    # there is none. This is `std/sys/debug.mojo:20`'s statement with a `return`
    # in front of it, and it must keep the same message the statement used to
    # get — a program that asked for the value of a trap is asking for something
    # no machine has.
    ("a_trap_in_a_value_position_is_still_refused",
     "def t() -> Int:\n"
     "    return __mlir_op.`llvm.intr.debugtrap`()\n",
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
    # …and the same program with an operand whose DECLARED type this build can
    # read. The clause about the operand is added and says nothing about the
    # OPERATION, which is the point: what is missing here is the predicate,
    # not the operand's type, and a clause that said "the operation is not the
    # ordinary spelling of anything" would be false of a comparison.
    ("an_unknown_predicate_over_a_word_operand_names_the_operand_not_the_op",
     "def bad(a: __mlir_type.index, b: __mlir_type.index) -> Int:\n"
     "    return __mlir_op.`pop.cmp`[pred=__mlir_attr.`#kgen.cmp_pred<nonesuch>`](\n"
     "        a, b)\n",
     "Its operand is declared '__mlir_type.index'",
     "applied ELEMENTWISE"),
    # A VECTOR operand, declared in the SOURCE rather than reached through a
    # `comptime` alias, and this is the row that makes the operand-type reader a
    # guard rather than a formality: 26 of the corpus's 38 arithmetic sites are
    # elementwise over an N-lane vector, and a table keyed on the operation name
    # would have lowered every one of them to a scalar add of two vector-typed
    # words. The refusal has to name the VECTOR, because the clause it replaces
    # said the operand type was the missing piece and here it is not.
    ("a_vector_operand_is_reported_as_a_vector_and_not_as_a_missing_type",
     "struct Vec:\n"
     "    var lanes: Int\n"
     "    var v: __mlir_type.`!kgen.simd<4, ui32>`\n"
     "\n"
     "def addit(a: Vec, b: Vec) -> Int:\n"
     "    return __mlir_op.`pop.add`(a.v, b.v)\n",
     "Its operand is declared '__mlir_type.`!kgen.simd<4, ui32>`', which is an "
     "N-LANE VECTOR",
     "no lowering table that establishes the operand type"),
    # A WORD operand on an operation the arithmetic table does not carry, which
    # is the third case the clause has to be able to say: the type IS
    # established, the result IS a word, and what is missing is the operation.
    # `pop.floordiv` is named in the message because it is the omission that
    # looks most like a gap in the table and is not one.
    ("a_word_operand_on_an_operation_this_path_does_not_compute_is_named_as_one",
     "def floored(a: __mlir_type.index, b: __mlir_type.index) -> Int:\n"
     "    return __mlir_op.`pop.floor`(a, b)\n",
     "What is missing is therefore the OPERATION rather than the type",
     "no lowering table that establishes the operand type"),
    # `std/simd.mojo`'s OWN spelling of the same operand, and the row that says
    # the reader reads a declaration and not a resolvable name: the field is
    # declared `Self._mlir_type`, which is a `comptime` ALIAS resolving to a
    # vector. Claiming the field's name without resolving the alias is what would
    # make this a scalar add, so the reader claims nothing and the refusal says
    # so.
    ("a_comptime_alias_operand_claims_nothing",
     "struct Vec:\n"
     "    comptime _mlir_type = __mlir_type[\n"
     "        `!kgen.simd<`, 4, `, `, `ui32`, `>`,\n"
     "    ]\n"
     "\n"
     "    var lanes: Int\n"
     "    var _mlir_value: Self._mlir_type\n"
     "\n"
     "def addit(self: Vec, rhs: Vec) -> Vec:\n"
     "    return Vec(lanes=0,\n"
     "               _mlir_value=__mlir_op.`pop.add`(self._mlir_value,\n"
     "                                              rhs._mlir_value))\n",
     "Nothing in the source states a type for this operand",
     "N-LANE VECTOR"),
    # A field of the SAME NAME on a base this function does not type. Measured
    # on this tree: `SIMDLength___init__(out self, value: Int)` writes
    # `__mlir_op.`pop.cast_to_builtin`[…](value._mlir_value)`, and a field table
    # keyed on the field NAME alone reported that operand as the `index` field
    # `SIMDLength` declares — a fact about the name rather than about the field
    # the source wrote, and one this row pins.
    ("a_field_of_the_same_name_on_an_untyped_base_claims_nothing",
     "struct Idx:\n"
     "    var tag: Int\n"
     "    var _mlir_value: __mlir_type.index\n"
     "\n"
     "def widen(value: Int) -> Idx:\n"
     "    return Idx(tag=0,\n"
     "               _mlir_value=__mlir_op.`pop.add`(value._mlir_value, 1))\n",
     "Nothing in the source states a type for this operand",
     "ONE 64-bit word here"),
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
    # `std/builtin/simd_length.mojo`'s six `index.*` operations and its six
    # `index.cmp`, which is every arithmetic site in the corpus whose operand is
    # declared a word — and the arithmetic table is why they now build. The
    # struct is TWO fields on purpose: a one-field struct's receiver IS its
    # field, so `self.v` is rewritten to `self` before this pass runs and the
    # operand stops being a declared `__mlir_type.index` at all.
    #
    # The expected values are STATED rather than taken from an oracle, because
    # CPython cannot parse `__mlir_op.`index.add`` — and because two of them are
    # not CPython's. `-7 // 2` is -4 in CPython and this path's `//` TRUNCATES,
    # which is `index.divs` and not `pop.floordiv`; `-7 >> 2` is -2 in both
    # because the shift is arithmetic. Those two are measured
    # (`bugs/FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops.md`'s
    # arithmetic table carries the measurement) and the row is what stops a
    # future edit to that table from quietly choosing floor division.
    ("a_dialect_arithmetic_lowers_when_its_operand_declares_a_word",
     "struct Idx:\n"
     "    var tag: Int\n"
     "    var v: __mlir_type.index\n"
     "\n"
     "def addit(self: Idx, rhs: Idx) -> Idx:\n"
     "    return Idx(tag=0, v=__mlir_op.`index.add`(self.v, rhs.v))\n"
     "\n"
     "def divs(self: Idx, rhs: Idx) -> Idx:\n"
     "    return Idx(tag=0, v=__mlir_op.`index.divs`(self.v, rhs.v))\n"
     "\n"
     "def anded(self: Idx, rhs: Idx) -> Idx:\n"
     "    return Idx(tag=0, v=__mlir_op.`index.and`(self.v, rhs.v))\n"
     "\n"
     "def shifted(self: Idx, rhs: Idx) -> Idx:\n"
     "    return Idx(tag=0, v=__mlir_op.`index.shrs`(self.v, rhs.v))\n"
     "\n"
     "def eqv(self: Idx, rhs: Idx) -> Int:\n"
     "    return 1 if __mlir_op.`index.cmp`[\n"
     "        pred=__mlir_attr.`#index.cmp_predicate<eq>`\n"
     "    ](self.v, rhs.v) else 0\n"
     "\n"
     "def lt(self: Idx, rhs: Idx) -> Int:\n"
     "    return 1 if __mlir_op.`index.cmp`[\n"
     "        pred=__mlir_attr.`#index.cmp_predicate<slt>`\n"
     "    ](self.v, rhs.v) else 0\n"
     "\n"
     "def main() -> Int:\n"
     "    var a = Idx(tag=1, v=-7)\n"
     "    var b = Idx(tag=2, v=2)\n"
     "    printf(\"%d %d %d %d\\n\", addit(a, b).v, divs(a, b).v, anded(a, b).v,\n"
     "           shifted(a, b).v)\n"
     "    printf(\"%d %d %d\\n\", eqv(a, a), eqv(a, b), lt(a, b))\n"
     "    return 0\n",
     "-5 -3 0 -2\n1 0 1\n"),
    # The same arithmetic in a KEYWORD ARGUMENT, and the row that is really a
    # regression pin for the shared walk: `CallExpr.kwargs` is a list of
    # `(name, value)` pairs, so a replacement that lands in one of them is in a
    # list nested inside a list. The walk that used to be written per pass
    # returned its empty accumulator for a list with a replaced element, which
    # set that list to `[]` — and the build died in
    # `model.struct_construction_plan` with `not enough values to unpack
    # (expected 2, got 0)`. A crash, out of a rewrite whose subject is an
    # addition.
    ("a_dialect_operation_lowers_inside_a_keyword_argument",
     "struct Idx:\n"
     "    var tag: Int\n"
     "    var v: __mlir_type.index\n"
     "\n"
     "def shifted(self: Idx, rhs: Idx) -> Idx:\n"
     "    return Idx(tag=0,\n"
     "               v=__mlir_op.`index.shrs`(self.v, rhs.v))\n"
     "\n"
     "def main() -> Int:\n"
     "    var a = Idx(tag=1, v=-7)\n"
     "    var b = Idx(tag=2, v=2)\n"
     "    printf(\"%d\\n\", shifted(a, b).v)\n"
     "    return 0\n",
     "-2\n"),
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
    # `std/sys/debug.mojo` verbatim, and the case the lowering exists for: a
    # dialect EFFECT whose value is DISCARDED has no result to represent, so the
    # refusal's own ground ("no representation in a 64-bit word, because there is
    # no value to represent") is absent at a statement, and refusing there cost a
    # whole module — the only IN-FILE refusal the `std/{os,sys}` scope carried.
    #
    # `want_stdout` is None rather than "" on purpose: the image DIVERGES, so it
    # must not be run here. `EMITTED` below is what checks what it emits, and a
    # case that ran this one could only ever see a nonzero exit.
    ("a_trap_statement_lowers_on_both_architectures",
     "def breakpointhook():\n"
     "    __mlir_op.`llvm.intr.debugtrap`()\n"
     "\n"
     "def main() -> Int32:\n"
     "    return 0\n",
     None),
]

# (name, mojo source, control source). Programs that must BUILD and must EMIT
# this path's divergence — which is a different question from `GUARDED`'s, and
# the one that would catch a lowering that quietly became a NO-OP.
#
# "The image differs from the control" is necessary and not sufficient: a trap
# lowered to nothing also differs, by nothing at all, and a reader would have no
# way to tell. So each architecture is asked for the fact it can report, and the
# split is a fact about the two backends rather than about the test — arm64
# inlines the syscall sequence (`movz x0,#1; movz x16,#1; svc #0x80`, read back
# through `formal/arm64.py`'s own encoder so no constant is written twice) and
# x86-64 binds the C library's `exit`, which the build reports in
# `info['external_syms']`.
EMITTED = [
    ("a_trap_emits_the_divergence_and_not_a_no_op",
     "def stop() -> Int:\n"
     "    __mlir_op.`llvm.intr.trap`()\n"
     "    return 0\n"
     "\n"
     "def main() -> Int:\n"
     "    return stop()\n",
     "def stop() -> Int:\n"
     "    return 0\n"
     "\n"
     "def main() -> Int:\n"
     "    return stop()\n"),
]

# ── THE SHARED WALK, asked directly ────────────────────────────────────────
#
# `a_dialect_operation_lowers_inside_a_keyword_argument` above pins the walk
# through a BUILD, and that is not redundant with what follows: a build is the
# only way the defect it guards was ever findable, because an emptied
# `kwargs` list took the build down in `model.struct_construction_plan` with
# `not enough values to unpack (expected 2, got 0)` — a crash, not a wrong
# answer, so it announced itself. What a build cannot do is pin the RULE, and
# the rule is the whole content of the walk: a child-rewriting walk has three
# container shapes and only two of them can return a replacement.
#
#     a single-attribute child   replaced through `setattr`
#     a TUPLE                    not assignable, so one with a replaced element
#                                comes back as a LIST and the slot it was read
#                                from takes it
#     a LIST                     assignable, so it is mutated IN PLACE and the
#                                caller has nothing to do
#
# The shape that was written in the two dialect walks kept a `changed` flag set
# from `repl is not None` for a LIST as readily as for a TUPLE, and returned the
# accumulator — which is empty for a list, because the list branch never appends
# to it. A list that is itself an ELEMENT of another list then had its parent's
# `node[i] = repl` fire on that empty list, and the elements were gone.
#
# Asked of `formal/build.py::_rewrite_dialect_in` rather than of a program
# because that is where the rule lives now: it is the one walk for both dialect
# passes, and its docstring states the rule. The last check below goes through a
# real PARSE, because `CallExpr.kwargs` being a list of `(name, value)` PAIRS is
# what makes a list nested inside a list reachable in this tree at all — the
# one shape the dialect walks can hit and the reason the defect was latent in
# `pop.select` and reachable in the arithmetic pass.
WALK_SOURCE = ("def f(a, b):\n"
               "    return g(a, tag=0, v=[h(a, b), b])\n")


def walk_rule_is_honoured() -> tuple:
    """The walk's container rule, on a real parse and on the bare containers.

    Returns `(ok, detail)`, the shape `census_is_complete` returns, so a failure
    here prints one row rather than a traceback out of a driver.  An EXCEPTION
    from inside is a failure and not a crash of this file: reverse-applied, the
    walk as the two dialect passes wrote it empties the list literal in check 4,
    and the `pairs[1][1].elements[0]` below is then an IndexError — which is the
    measured symptom (`not enough values to unpack (expected 2, got 0)`, one
    level further on) arriving through the check instead of through a build.  A
    pin that raises is a pin that fails for the wrong reason.
    """
    try:
        return _walk_rule()
    except Exception as e:                          # noqa: BLE001
        return False, (f"{type(e).__name__}: {e} — the walk emptied a container "
                       f"it was supposed to mutate in place, so the tree it was "
                       f"handed no longer has the shape it started with")


def _walk_rule() -> tuple:
    sys.path.insert(0, HERE)
    import fire_compiler as F
    import formal.build as B
    import formal.model as M
    bad = []

    # 1. A list inside a list — the shape that emptied. Plain Python containers,
    #    because the walk is generic over list/tuple/dict and this is the shape
    #    itself rather than any particular node that holds one.
    a, b, c, d = object(), object(), object(), object()
    inner = [a, b]
    outer = [inner, c, d]
    count = [0]
    got = B._rewrite_dialect_in(outer, lambda n: "R" if n is b else None, count)
    if got is not None:
        bad.append(f"a list returned {got!r}; a list is mutated in place and "
                   f"never returned, or its parent's element assignment "
                   f"overwrites it")
    if outer[0] is not inner or inner != [a, "R"] or outer[1:] != [c, d]:
        bad.append(f"the nested list came back as {outer!r}; a replacement in "
                   f"it must land in place with every other element intact")
    if count[0] != 1:
        bad.append(f"one replacement counted {count[0]} times, not once")

    # 2. A tuple: replaced element comes back as a LIST, untouched tuple comes
    #    back as None — and the None is load-bearing, because it is what keeps
    #    the common case from rewriting the list the tuple lives in.
    got = B._rewrite_dialect_in((a, b), lambda n: "R" if n is b else None, [0])
    if got != [a, "R"]:
        bad.append(f"a tuple with a replaced element came back as {got!r}; it "
                   f"is not assignable, so it comes back as a LIST")
    got = B._rewrite_dialect_in((a, b), lambda n: None, [0])
    if got is not None:
        bad.append(f"an untouched tuple came back as {got!r}; returning a copy "
                   f"of it would rewrite every list it lives in")

    # 3. `_KEEP_WHOLE`: left whole AND not descended into, which is what a
    #    dialect template this build cannot answer needs.
    stmts = F.Parser(F.py_tokenize(WALK_SOURCE)).parse_module()
    call = stmts[0].body[0].value
    inner_call = [n for n in M.iter_nodes(call)
                  if isinstance(n, F.CallExpr)
                  and getattr(n.func, "name", None) == "h"][0]
    kept = B._rewrite_dialect_in(
        call, lambda n: B._KEEP_WHOLE if n is inner_call else None, [0])
    if kept is not None or inner_call not in list(M.iter_nodes(call)):
        bad.append("a `_KEEP_WHOLE` node was descended into or returned")

    # 4. The reachable shape, on a real parse: a replacement inside a keyword
    #    argument, whose value is a list literal — a list nested inside the list
    #    of `kwargs` pairs. `call.kwargs` must still be two pairs afterwards,
    #    which is exactly what `not enough values to unpack` was about.
    count = [0]
    got = B._rewrite_dialect_in(call, lambda n: "R" if n is inner_call else
                                None, count)
    pairs = call.kwargs
    if got is not None:
        bad.append(f"the outer call came back as {got!r}; it was not replaced, "
                   f"so the walk answers None and the caller's slot keeps it")
    if count[0] != 1 or len(pairs) != 2 or any(len(p) != 2 for p in pairs):
        bad.append(f"kwargs came back as {pairs!r} after {count[0]} "
                   f"replacement(s); two pairs of two is what the frame-"
                   f"argument reader unpacks")
    if pairs[1][1].elements[0] != "R" or len(pairs[1][1].elements) != 2:
        bad.append(f"the list literal in the keyword argument came back as "
                   f"{pairs[1][1].elements!r}; its other element is gone")

    if bad:
        return False, ("; ".join(bad))
    return True, ("a list is mutated in place and never returned, a tuple with "
                  "a replacement comes back as a list, and the keyword-"
                  "argument list survives a replacement in it")


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


def run_emitted(name, source, control, tmpdir, verbose):
    """Both architectures must BUILD both programs and EMIT the divergence.

    `compile_formal` is called directly rather than through `fire.py` because
    the assertion is about the artifact and the build's own report, and the
    report (`info['external_syms']`) is not printed by the CLI. The control is
    the same program with the statement replaced by nothing, so "the image
    changed" and "the image changed into the divergence" are two separate
    claims and both are made.
    """
    sys.path.insert(0, HERE)
    import formal.arm64 as A
    import formal.build as B
    paths = {}
    for tag, text in (("trap", source), ("control", control)):
        p = os.path.join(tmpdir, f"{name}.{tag}.mojo")
        with open(p, "w") as f:
            f.write(text)
        paths[tag] = p
    for backend in ("arm64", "x86_64"):
        built = {}
        for tag in ("trap", "control"):
            out = os.path.join(tmpdir, f"{name}.{tag}.{backend}")
            try:
                built[tag] = B.compile_formal(paths[tag], output=out,
                                              prove=False, arch=backend)
            except Exception as e:                     # noqa: BLE001
                return False, (f"--backend={backend} refused the {tag} program: "
                               f"{e}")
        if built["trap"]["code"] == built["control"]["code"]:
            return False, (f"--backend={backend} emitted the SAME words for the "
                           f"trap and for the control, so the statement lowered "
                           f"to nothing at all")
        if backend == "arm64":
            svc = A.encode_svc(0x80)
            got = built["trap"]["code"].count(svc)
            want = built["control"]["code"].count(svc)
            if got <= want:
                return False, (
                    f"--backend={backend} emitted {got} `svc` and the control "
                    f"{want}, so the divergence this path's `raise` emits is not "
                    f"in the image the trap produced")
        else:
            syms = built["trap"]["info"].get("external_syms") or []
            if "exit" not in syms:
                return False, (
                    f"--backend={backend} emitted no `exit` call "
                    f"(external symbols: {sorted(syms)}), so the trap did not "
                    f"diverge through the sequence `_emit_diverge` shares with "
                    f"`raise`")
    if verbose:
        print(f"      emitted the divergence on arm64 and x86-64, and the "
              f"control emits none")
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
             | {c[0] for c in GUARDED} | {c[0] for c in EMITTED})
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
        for name, source, control in EMITTED:
            if args.cases and name not in args.cases:
                continue
            try:
                checks.append((name,) + run_emitted(name, source, control,
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

        # The walk's container rule, asked of the walk. Also not a property of
        # any one build, and it COUNTS in the tally rather than printing beside
        # it: the census above can be SKIPPED for want of a corpus, this cannot
        # be skipped at all, and a check whose failure did not reach the exit
        # code would be a check nobody runs.
        ok, detail = walk_rule_is_honoured()
        checks.append(("the_shared_walk_mutates_a_list_in_place_and_never_"
                       "returns_one", ok, detail))

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