#!/usr/bin/env python3
"""Rank the TERMINAL causes of a `tools/formal_sweep.py` log.

`formal_sweep.py` classifies every file and prints one line per non-pass, and
its per-family breakdown groups by the SHAPE of the message. That is the right
grouping for a tool that must classify a message it has never seen, and the
wrong one for a person deciding what to work on next: `other refusal` was the
largest bucket in the 2026-09-30 run at 32 files, and it held nine different
constructs. This ranks by what a fix would have to CHANGE.

WHAT A "CAUSE" IS, and why it is not a message
----------------------------------------------
Every printed line of class `codegen` / `codegen/dependency` is peeled to its
terminal message with `formal_sweep.py`'s own `_split_chain` / `_terminal_reason`
(so the chain is followed to the end rather than read at its outermost layer),
the `<file>: <Func>:` noise is stripped, and the result is keyed on a coarse
label. One cause in six modules is one fix that moves six modules; one cause in
one module is a fix that moves one file and says nothing about the other five.

The count is FILES BLOCKED — printed lines, so a dependency chain contributes
one line to the cause at its end and nothing to the cause at its top.

THE COUNT IS AN UPPER BOUND, and this tool says so rather than implying
otherwise. A file's terminal cause is the FIRST refusal the build's walk
reaches, so a module is typically behind a stack of two to four of them, and
fixing one moves the file to the next with the count unchanged. Two causes were
measured this way on 2026-09-30 and BOTH had a ceiling of zero files — see
`bugs/FORMAL_sweep_work_map_2026-09-30.md` §3. The current map, which every
number below comes from, is `bugs/FORMAL_sweep_work_map_2026-09-30_r2.md`.
Nothing here can tell you a cause's real value; only re-sweeping the files it
blocks can.

OF THOSE FILES, HOW MANY EVEN NAME WHAT THE REFUSING MODULE DECLARES
---------------------------------------------------------------------
`FILES BLOCKED` answers "how big is this row", which is the wrong first
question for a cause whose refusal is about a MODULE rather than about a
construct in the file that was swept. The formal backend builds a dylib for
every module in a file's EAGER import closure (`formal/imports.py`'s
`build_module_dylib`), so a module with no boundary symbol refuses every
importer of its importers — whether or not any of them binds a name in it.
The 2026-09-30 r2 sweep's second-largest row was 38 files on exactly that
refusal, 35 of them behind `std/collections/binary_heap.mojo`, and 34 of THOSE
35 do not contain the string `BinaryHeap` anywhere: they are refused for a type
in a module one line of `std/collections/__init__.mojo` re-exports.

So `uses:` below, per refusing module: how many of the files it blocks name
anything it declares. It is computed from `reflect.export_exclusions` — the one
export rule, the same function the refusal message is built from — and the
declared names are printed with it, so a reader can check the search rather
than trust it. `0 of 35` next to a row of 35 is the difference between "38
files of work" and "38 files waiting on a Stage 5 dependency", and it is the
number that says which. Measured ceilings for that row: 0 files reach `pass`
under either probe (`bugs/FORMAL_dylib_export_gate_ceiling.md`).

THE MARKERS ARE AND-WITHIN / OR-WITHIN, and both halves are load-bearing
-------------------------------------------------------------------------
Each cause is a tuple of ALTERNATIVES and an alternative is a tuple of
substrings that must ALL be present; the cause matches when ANY of its
alternatives is fully present. So `(a,)` OR `(b,)` is two wordings of one
construct, and `(a, b)` is one construct that says both.

Both halves have been got wrong here, in opposite directions, and the second
is the more dangerous one:

  * OR within an alternative, with the alternatives collapsed into one AND —
    the 2026-09-30 draft listed one cause as any of `reads '` / `out of a
    nested` / `has no such field`, matched on `reads '` alone, and reported
    11 files for a cause that has 4. The two outputs are indistinguishable and
    differ by 7, so a count is only as good as its operator.
  * AND across what were alternatives — the MLIR cause was written as three
    sub-groups, one per wording (`is initialized from an MLIR attribute
    template`, `__mlir_attr[`, `__mlir_op is an MLIR dialect construct`), so it
    required a message containing all three, matched nothing, and let 107
    findings fall through to whichever broad cause came next in the list. The
    symptom is a large cause with a nonsensical name and an example that has
    nothing to do with it, which is at least loud; the OR failure above was
    quiet.

ORDER is most specific first and first match wins, so a broad marker placed
early swallows everything under it. Two boundaries matter and both are
load-bearing: `callee has no definition on this path` is asked before
`receiver passed at argument position 0` (they share `… is passed to …`, and
asking the other way round puts 12 findings in the wrong column), and
`frame address passed where a value is wanted` is asked before the same pair.

A MARKER IS A CONTRACT WITH A MESSAGE THAT CAN BE REWORDED, and breaking it is
invisible from here
-----------------------------------------------------------------------------
A marker is a quoted substring of a message `formal/` owns. When a worker
rewords that message — which is a routine improvement, and a good one — every
cause keyed on the old wording silently drops to zero and its files fall into
`other refusal`, which is the bucket that means "this tool has not classified
this". That is the quiet failure mode again, one level up: nothing raises, the
table still sums to the total, and the number that changed is the number a
planner would act on. It happened here for real between the two 2026-09-30
sweeps: `formal-module-attr` reworded `… so it is a module-level name of
another module` into `… and it is a module-level name of another module`, and
4 findings walked out of that row into `other refusal` with nothing to show
for it.

So this table lists BOTH wordings where a message has had one, and — the part
that keeps doing it from happening again — `test_formal_sweep.py` asserts that
every marker matches at least one refusal the sweep actually produced, by
building the message from `formal/`'s own text rather than from a copy in the
test. A reword that breaks a marker fails a test instead of quietly moving a
column.

    python3 tools/formal_sweep_causes.py .tmp/sweep.log          # the table
    python3 tools/formal_sweep_causes.py --json .tmp/sweep.log   # machine-readable
    python3 tools/formal_sweep_causes.py --min 5 .tmp/sweep.log # only above N files

Exit status is 0 whenever the log was read, including when every cause is
non-empty: this tool reports on other tools' output and has no opinion about
whether any of it is a defect.
"""
import argparse
import collections
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _load_sweep():
    """`formal_sweep.py`, loaded by path.

    By path rather than by import because that file is a script whose
    `__main__` does the sweep, and importing it for its two regex helpers
    should not be able to start one.
    """
    spec = importlib.util.spec_from_file_location(
        "formal_sweep_under_test", os.path.join(HERE, "formal_sweep.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FS = _load_sweep()

# One printed line: `CLASS: path  (detail)`. The class is upper case and may
# itself contain `/` and `-` (not-answerable/host-import), which is why the
# character class has them.
LINE_RE = re.compile(
    r"^(?P<cls>[A-Z][A-Z/ -]*?): (?P<path>\S+)\s+\((?P<detail>.*)\)\s*$")
# There is deliberately NO `<Func>: ` strip, and a first version of this tool
# had one and got it wrong in a way worth recording. formal/imports.py prefixes
# a message with the file it came from and a lifted method carries its own
# `Owner_method: ` prefix, so it is tempting to strip a leading identifier
# before matching. The regex that did so also matched the first WORD of any
# message whose first word is an identifier — "the module-level comptime binding
# '_mIsSigned' is initialized from an MLIR attribute template" lost its "the",
# and 107 MLIR findings fell through to whatever came next in the list. The
# prefixes are cosmetic: every marker below is a distinctive clause that no
# prefix can hide, and the example line printed per cause keeps the whole
# message, because the file and the function the refusal really came from are
# the useful half of it.

# THE VOCABULARY. Ordered most specific first; first match wins. Every marker is
# a substring quoted from a message the 2026-09-30 arm64 sweep actually
# produced. Within a cause: the outer tuple is a set of ALTERNATIVES (any one
# matching is enough) and each alternative is an AND of substrings.
CAUSES = (
    # ── limits of the TARGET, not of the backend. ──
    # Three wordings of ONE construct, so three alternatives and not one AND.
    # FOUR wordings of ONE construct, and the fourth is the one this table was
    # MISSING until the 2026-10-01 b3 sweep: `formal/model.py` computes the kind
    # from the node (`kind = "type" if is_mlir_type_template(node) else
    # "attribute"`) and says "an MLIR type template" for `__mlir_type.`!kgen
    # .target``, so a message carrying the TYPE spelling satisfied none of the
    # three markers and fell into `other refusal`. 5 files measured
    # (`std/_gpu/_utils.mojo`, `std/builtin/{_coroutine,enum_like,type_aliases}
    # .mojo`, `std/sys/info.mojo`), and the label already named `__mlir_type`,
    # so the row claimed a construct it could not see.
    # A FIFTH wording, and the one that needs the most care: `formal/model.py`'s
    # `mlir_dialect_op_refusal` used to answer every `__mlir_op` with ONE
    # sentence, and it named the `__mlir_` PREFIX rather than the operation. It
    # now classifies the OPERATION by what it denotes — an effect, an
    # elementwise arithmetic result, or a value that needs a fact this path
    # lacks — so four different messages carry the word "dialect OPERATION" and
    # one carries the old prefix wording for a caller with no operation in hand.
    #
    # Both spellings are listed, because a marker is a CONTRACT WITH A MESSAGE
    # THAT CAN BE REWORDED and breaking it is invisible from here: every cause
    # keyed on the old wording silently drops to zero and its files fall into
    # `other refusal`. `test_formal_sweep.py` asserts every marker matches a
    # refusal the sweep actually produced, by building the message from
    # `formal/`'s own text rather than from a copy in the test, so a reword that
    # broke a marker fails a test rather than quietly moving a column — but only
    # for a marker a sample exercises, which is why there is a sample per
    # wording below rather than one for the row.
    ("MLIR dialect construct (__mlir_attr / __mlir_type / __mlir_op)",
     (("is initialized from an MLIR attribute template",),
      ("is initialized from an MLIR type template",),
      ("__mlir_attr[",),
      ("__mlir_op is an MLIR dialect construct",),
      ("is a dialect OPERATION",))),
    ("inlined_assembly (a gimple-C runtime construct)",
     (("inlined_assembly:",),)),
    # ABOVE the broad `has no representation` cause below, and it has to be:
    # `model.multi_index_refusal` ENDS with "so a tuple index has no
    # representation on this path", so a multi-index message satisfies both and
    # first match wins. Asked the other way round this cause collects nothing
    # forever and nothing says so — the precedence failure this file's sibling
    # test (`test_refusal_taxonomy.py`) exists to catch, in the table that
    # ranks the causes rather than the one that summarises them.
    ("multi-index subscript",
     (("is a subscript whose index is a tuple",),)),
    # ABOVE the two rows below it, and for a reason that is a fact about the
    # messages rather than about this construct: they are all one family — a
    # representation the target does not have — and the broad ones end with a
    # sentence the specific ones also contain. 20 files on BOTH architectures,
    # every one of them `std/builtin/builtin_slice.mojo`'s `self.step.or_else()`,
    # and the module docstring's `uses:` column reads 0 of 20 name anything it
    # declares, because the refusal is about `builtin_slice`'s own line rather
    # than about the importing file. So this row is one value-model change
    # (Optional needs a niche, a discriminant or a tag word) whose OWN doc is
    # `bugs/FORMAL_struct_construction_shapes.md`, and its measured landing is
    # recorded there: the same line used to refuse with a FALSE reason
    # ("constructing Slice with 3 argument(s)") and now refuses with a true
    # one.
    ("Optional unwrap: `None` and a value are one word, with no tag",
     (("is an Optional unwrap",),)),
    ("value with no representation on this path",
     (("has no representation on this path",),
      ("has no representation for",))),
    ("module exports no public functions",
     (("has no public functions",),)),
    ("a linked module exports no such name",
     (("is a linked module but it exports no",),)),

    # ── a NAME the walk cannot place. Five different reasons, five different
    #    bugs, and the one-word value model is the reason several of them say
    #    what they say. ──
    # ONE cause, not two, and the reason is a limit of the LOG rather than of
    # the taxonomy: `List[Self.T]()` and `DType.bool` produce the SAME terminal
    # message shape ("<Func>: '<Name>' has no home: …"), because the difference
    # is in the AST — whether the refused IdentExpr is the base of a SUBSCRIPT
    # callee or of a MemberExpr — and the printed line does not carry the AST.
    # Splitting them here would mean keying on the refused NAME, which is a list
    # that rots, and it would be a list this repo already has to maintain twice
    # over. So they are one row, the refused-name histogram separates them for a
    # reader who needs to, and `names` is printed per cause for exactly that.
    ("a TYPE name placed as a value (`L[T]()` or `DType.bool`)",
     (("has no home",),)),
    ("a module-global name has no storage",
     (("is bound at module level, and this path has no module-global storage",),)),
    ("a module-level name of ANOTHER module is not exported as a word",
     # TWO wordings, because the message has been reworded once and the
     # earlier wording is what the 2026-09-30 sweep log still contains — the
     # log is an artifact, so a table that only knows the new wording silently
     # reads an old log as `other refusal`. See the module docstring.
     (("so it is a module-level name of another module",),
      ("and it is a module-level name of another module",))),
    # The DOTTED spelling of the same boundary, which is a different construct
    # and has its own row rather than joining the one above. `mod.NAME` reads
    # an ATTRIBUTE of a module; `from mod import NAME` then `NAME` reads the
    # name itself. Both are refused, for the same underlying reason and with
    # two different messages, and before this the dotted one was refused with
    # the BARE one's message — about a storage problem for a name that is a
    # MODULE and needs none. Keyed on the clause that is unique to the new
    # message ("a module is not a value this path can place"), which is why the
    # two rows cannot collide: the bare message does not contain it.
    ("a module's ATTRIBUTE read as a value, across a dylib boundary",
     (("is not a value this path can place",),)),

    # ── the frame / receiver families. The by-reference receiver design, and
    #    each of these is one of its bands. ──
    ("method parameter's field, with no call site to establish it",
     (("is a field access",),)),
    ("frame address escapes: returned by its creator",
     (("is returned from the function that created it",),)),
    ("frame address escapes: aliased out of a method",
     (("did not create the frame",),)),
    ("frame address passed where a value is wanted",
     (("frame address is passed to",),)),
    # The INVERSE of the row above, and it was unclassified until the
    # 2026-10-01 b3 sweep: there the CALL wants a frame address and the SLOT
    # does not establish one, so the walk cannot tell whether the word in the
    # slot is the address the callee will dereference. `formal/build.py:2731`
    # says "hands the word in the slot X to M.method(), whose receiver is the
    # ADDRESS of a frame of 8-byte slots — so the slot would have to hold a
    # frame address", which shares no substring with the row above's "frame
    # address is passed to". 3 files, all in-file, on both architectures. The
    # fix the message names is the same one for all three ("Only a type for
    # '…' could say so"): every binding of the name has to agree on one type.
    #
    # This row also ABSORBS the one it used to be two of. The same site has
    # reworded its TAIL once — "The declared type of 'scope' is the only thing
    # here that could say so, and it does not: <reason>" became "Only a type for
    # 'scope' could say so … and there is no single one: <reason>" — and the
    # old row's markers were both in that tail, so after the reword it collected
    # ZERO files while reading as a live cause. The shared first sentence is
    # what both wordings have, which is why this row's marker is that sentence
    # and one alternative covers both. The old wording is kept as a sample in
    # `test_refusal_taxonomy.py` precisely so this cannot happen silently again.
    ("the slot would have to hold a frame address, and no type says so",
     (("hands the word in the slot",),)),
    # A name that holds a frame address and is then REBOUND by an assignment,
    # so which frame it names depends on which function ran the store. Two
    # wordings of that one construct, from two different walkers:
    # `formal/build.py`'s placed-frame analysis ("but a method of SwissTable
    # ASSIGNS that field") and `formal/model.py:10754` ("atom is assigned … and
    # atom also holds the address of a Repeat frame"). 3 files on arm64, 3 on
    # x86-64. Measured, and the reason it is refused rather than lowered: with
    # nothing lifted the shape builds, runs, and dies with SIGSEGV (exit 139).
    ("a slot holding a frame address is rebound by a later assignment",
     (("but a method of", "ASSIGNS that field"),
      ("also holds the address of a",))),
    ("receiver stored in a container",
     (("receiver is stored in a container",),)),
    # The FIELD sibling of the row above, and it was unclassified until the
    # 2026-10-01 b3 sweep: `formal/build.py`'s `AssignStmt`-to-`MemberExpr`
    # branch passes "is stored in the field …, so it outlives the frame it
    # names", which shares no substring with the container branch's wording.
    # 22 files in-file on both architectures, the largest unclassified row in
    # the b3 sweep. It is a different construct from the container row — a
    # field has an owner that outlives the call, a container does not — so it
    # is its own cause and not an alternative of that one.
    ("receiver stored in a field of a struct that outlives it",
     (("is stored in the field",),)),
    ("a field of a field: a frame slot holds one word, not a struct",
     (("reads a field of a field",),)),
    ("a field of a nested frame that the struct does not declare",
     (("out of a nested",),)),
    # A field the candidate struct does not declare AT ALL, which is a
    # different refusal from the row above (that one is about a frame the
    # struct has not been told the layout of; this one is about a name that is
    # not a field of the struct it is read through). `formal/model.py:14270`
    # and `:14288` are the two sites and they word it differently, so two
    # alternatives. 5 files, all in-file, identical on both architectures.
    #
    # It gets a row of its own because the row is a bucket of MESSAGES and
    # those 5 files are TWO constructs, which is the lesson
    # `FORMAL_subscripted_method_callee_and_three_level_nested_frames.md`
    # records for an earlier row and which no marker can express: the same
    # sentence is produced whether the name is missing (3 of the 5 — and for
    # those, CPython raises `AttributeError`, because nothing in the tree ever
    # assigns the name) or present as a `comptime` class member (2 of the 5,
    # correct Mojo that raises nothing). The census now reaches an IMPORTED
    # module's classes (`formal/imports.py`'s `_attach_declared_census`), so
    # what is left in that second arm is a member whose VALUE is not a literal
    # — a true refusal about a value this path cannot materialise. So the label
    # still claims neither: the per-file split is in
    # `bugs/FORMAL_sweep_work_map_2026-10-01_b3.md`, and a reader who trusts
    # the message's own "In Python this is an AttributeError" clause will be
    # wrong about 2 of these 5.
    ("a field the struct does not declare (missing, or a comptime member)",
     (("is a field of", "has no field"),
      ("is a field of", "NO candidate has field"))),
    ("a slot's declared type is not declared by its struct",
     (("is the only thing here that could say so",),
      ("does not declare",))),
    # ^ ZERO files on the 2026-10-01 r2 sweep, both architectures, and that is
    # the rot this table's sibling test exists to catch: the site reworded its
    # tail and both markers went with it. Superseded by the row two above,
    # which owns the sentence both wordings share. Kept, because the same site
    # can reword again and a table that forgets the old wording reads an old
    # log as unclassified — but it is DEAD, and a reader should price it at 0.
    ("a name holds a frame address in more than one shape",
     (("holds a frame address in more than one shape",),)),
    ("one parameter, two kinds of value across call sites",
     (("One parameter, two kinds of value",),)),
    # The DECLARED-TYPE sibling of the row above — `frame_declared_parameter_
    # refusal` rather than `frame_holder_disagreement_refusal` — and the two
    # are different rules, so they are different causes. That one compares the
    # call sites with EACH OTHER; this one compares them with the parameter's
    # own annotation, which is the only evidence there is when no call site ever
    # passed a frame. Its marker was absent until the 2026-10-01 b3 sweep, so
    # 13 files sat in `other refusal` naming a construct this table claims to
    # cover. Placed BELOW the row above deliberately: the two messages share no
    # substring, so the order between them is documentation, not precedence.
    ("a parameter's declared type contradicts every call site",
     (("every call site in this image hands it something else",),)),
    ("a slot's declared type is not a value this path can supply",
     (("this slot's DECLARED type is",),)),

    # ── a callee this image has no definition of. Asked BEFORE the pair below,
    #    which shares `… is passed to …`. ──
    ("callee has no definition on this path",
     (("which is a name with no definition in hand",),)),
    # `f[…](x)` on a callee THIS UNIT DOES NOT COMPILE. This is the single
    # largest row in the 2026-10-01 b3 sweep — 93 files on BOTH architectures,
    # 85 of them the `debug_assert[…]` in `std/collections/binary_heap.mojo`
    # alone — and it had NO marker, so the whole row was inside `other
    # refusal`. That is the same defect the `==` row below records, one order
    # of magnitude larger, and it is the row a planner most needs: it is one
    # builtin with no lowering at all
    # (`bugs/FORMAL_debug_assert_bracket_has_no_lowering.md`).
    #
    # Above `callee has no definition` deliberately. The two messages are about
    # the same callee and share no substring — that one says "a name with no
    # definition in hand", this one "calls a name this unit does not compile" —
    # so today the order is documentation. It is pinned by
    # `test_refusal_taxonomy.py` so it stays that way in BOTH directions.
    ("a bracketed specialization of a callee this unit does not compile",
     (("so the brackets cannot be bound",),)),
    ("receiver passed at argument position 0",
     (("in argument position",),)),
    ("receiver passed to a call, position not stated",
     (("is passed to",),)),

    # ── the remaining shapes, each with its own next step. ──
    ("struct construction: arity does not match the fields",
     (("does not match its fields",),)),
    ("a `...` body: no instructions to emit",
     (("stands where this path needs instructions",),)),
    # 37 files on the 2026-09-30 r2 sweep, and 36 of them are ONE stdlib host
    # module refusing on ONE comparison — the largest single construct in the
    # whole table, and it was in `other refusal` until this marker existed.
    # `other refusal` is the bucket that means "unclassified", so a construct
    # this large sitting in it is not a rounding error in a reader's
    # judgement; it is the tool declining to do the one job it exists for.
    ("`==` between two values whose kind no call site established",
     (("compares two values this path can only call numbers",),)),
    ("print() cannot classify the argument's type",
     (("cannot tell whether",),)),
    ("len() of a value that has no length",
     (("is len() of a value classified as",),)),
    ("write(2) receiver is not a file descriptor",
     (("lowers to the C library's write(2)",),)),
    ("a method on a multi-field struct where a descriptor is meant",
     (("is a method on a Writer",),)),
    # TWO wordings of ONE construct, and it was the largest per-architecture
    # difference in the whole sweep: 56 files on x86-64 and 0 on arm64, all of
    # them one ABI constant.  The markers quote the ABI NAME and never the
    # number, which is the property that matters here — a table keyed on
    # "exceeds the 8" cannot see a target that passes six.
    #
    # **The ceiling in the NAME is a 2026-10-01 measurement and no longer
    # fires.**  Both backends implement their ABI's stack-argument convention
    # now (`_MAX_INCOMING_ARGS` = 24 in each, a FRAME bound: every parameter
    # past the register file needs a home), so this sentence appears at
    # twenty-five arguments on BOTH machines instead of at nine on arm64 and
    # seven on x86-64, and the register counts it names are the REGISTER half
    # of a split rather than the limit.  The name is left alone deliberately:
    # it is the key every sweep log and every dated work-map table in
    # `bugs/` is written against, and renaming it under the round's other
    # sweeps would leave their tables naming a cause the tool no longer emits.
    # The markers below are therefore the live ones — `the formal <arch> ABI
    # passes`, with no `in registers` — which match BOTH wordings, so a sweep
    # taken before the convention and one taken after it classify the same
    # construct into the same row.  Dropping `in registers` is what makes the
    # x86-64 half of that true: the new message ends `...(6 in registers and 18
    # on the stack)`.
    #
    # What it cost while it was the register count, for the record: the host
    # module `formal/hostmods/fnmatch.mojo` — `match_core(7)`, the one
    # over-wide function left in `formal/hostmods` — and everything importing
    # it, which is `pathlib` and then four files in `tools/`.
    # `test_formal_hostmods_census.py` is the per-module, per-backend table.
    ("too many parameters for the register ABI (8 on arm64, 6 on x86-64)",
     (("the formal arm64 ABI passes",),
      ("the formal x86-64 ABI passes",))),
    # A NUMBER compared with a STRING. Not the `==` row further down: that one
    # is about a comparison between two values no call site classified, and
    # this one is about the OPERANDS being of kinds that cannot be compared
    # here at all — `_v == '1'` would lower to `strcmp`, which dereferences
    # both operands, so the number would be handed over as an address.
    # Measured on this tree (in the message): `p[0] != "."` on a
    # `Pointer[UInt8]` segfaults with no output. 3 files on arm64, 1 on
    # x86-64; Python has no such comparison at all, which is why the row is
    # worth naming separately from the `==` one.
    ("a NUMBER compared with a string (`strcmp` would dereference it)",
     (("NUMBER with a string",),)),
    # A module-global container that HAS storage and no initializer, which is
    # the other half of `a module-global name has no storage` above: there the
    # slot does not exist, here it exists and nothing can be put in it before
    # the program runs. 3 files (2 on x86-64), in-file on all of them.
    ("a module-global container has storage but no initializer",
     (("has no initializer",),)),
    # The ORDER half of the same capability, and it is a separate cause because
    # the two have different repairs. The row above is a name whose value the
    # build cannot compute at all; this one is a name it CAN compute, in a
    # `__DATA` slot the module's own top-level statements fill, read before that
    # fill happens. Before the storage question existed the two were
    # indistinguishable — one message for both — and giving the slot to every
    # name the module body writes turned the second into its own refusal, which
    # is what makes the distinction visible here rather than in the reader's
    # head.
    #
    # Placed here, NEXT TO `a module-global container has storage but no
    # initializer`, and keyed on a clause only this message carries. The two
    # messages name the same thing — a `__DATA` slot with no value in it yet —
    # and the sibling one says so with `has no initializer`; the marker here is
    # the sentence about the MODULE BODY, which that one cannot contain. Keyed on
    # the shared part instead, this row would swallow the sibling's files, which
    # `test_refusal_taxonomy.py` caught by building both messages out of
    # `formal/`'s own text and asking which cause each lands in.
    ("a module global the module BODY fills, read before it fills it",
     (("is one of the module-global slots in this image's",),
      ("which this path compiles into the synthetic function the startup stub "
       "enters",))),
    # `field(default_factory=F)` — the dataclass transform needs one value per
    # instance, and this path has nowhere to keep it: not module-global
    # storage, and a local in the constructor's frame dies with the
    # constructor. 2 files, in-file, both architectures.
    ("`field(default_factory=F)`: nowhere to keep a per-instance value",
     (("calls F once per instance",),)),
    # A constructor called WITH arguments, whose body is not a bare sequence
    # of `self.<field> = …` assignments. The inlining this path does can
    # store the assignments at the construction site; a body that READS `self`
    # (or branches, loops, or calls a method) needs the block's address
    # threaded through, which has no lowering here. 2 files, in-file.
    ("a constructor body that reads `self` is not inlined",
     (("whose body this path does not inline",),)),
    # A module whose API IS its top-level statements, imported by another
    # module: this path compiles an import into a dylib, and a dylib has no
    # entry point to run a module body at load time, so the module would build,
    # link, and do nothing — the silent no-op one level down from the
    # executable path's own. Distinct from `module exports no public
    # functions` (which is about what a dylib PUBLISHES): this is about
    # whether it would RUN anything. 2 files + their importers on both arches.
    ("a module whose API is its top-level statements, imported by another",
     (("this module's API is its top-level statements",),)),
    # A local read before anything in the function stores it. `formal/build.py`
    # enforces this for module-global names and not for locals, which is what
    # `bugs/FORMAL_a_local_read_before_its_first_assignment.md` measures; 1
    # file, in-file. Below the bar a cause clears to be worth a row, and here
    # anyway: a cause with a doc and no marker is a cause nobody can find from
    # the table.
    ("a local read before its first assignment",
     (("before anything in this function stores it",),)),
    # ── the two x86-64-only refusals, which are arch DRIFT rather than a
    #    construct. Both are recorded, with this exact wording, in
    #    `bugs/FORMAL_known_limits.md` §6.5 as the two files whose message
    #    differs between architectures on an otherwise class-identical sweep —
    #    and neither had a marker, so the instrument could not show the drift
    #    the doc had already measured. `swap.mojo` BUILDS on arm64 and is
    #    refused here; `polynomial.mojo` is refused on both arches for the same
    #    `comptime` line, under two different names.
    ("an operator the x86-64 codegen does not lower",
     (("unsupported unary operator",),)),
    ("a call target the x86-64 codegen does not lower",
     (("unsupported call target",),)),
    ("comptime does not fold to a constant",
     (("does not fold to a compile-time constant",),)),
    ("variadic call has no ABI",
     (("has no variadic ABI",),)),
    # (`unimplemented intrinsic` was a cause here until 2026-09-30 r2, and it
    # was DEAD twice over: its marker was the FAMILY NAME from
    # `formal_sweep.py`'s `_REFUSAL_FAMILIES` rather than anything a message
    # contains — no message anywhere in the tree says "unimplemented
    # intrinsic" — and the message it was written for is the `...`-body
    # refusal three entries above. A duplicate with a dead marker is worse
    # than no row: it reads as a cause that blocks nothing, which is
    # indistinguishable from a cause nothing is blocked by.)
    ("method call on a value receiver is not one of the lowered methods",
     (("lowers only append, close, write",),)),
    # A class-level default that is a literal-looking expression whose value is
    # NOT materializable here (a call, a computed name) rather than one the
    # build can fold. 1 file, in-file, both architectures
    # (`formal/dataclass_transform.py`'s `field_refusal`).
    #
    # This row used to have a sibling above it, for the case where the default
    # is the NAME `None` — `None` parses to `IdentExpr('None')` on this parser
    # and is not a literal, so there was nothing to materialize. It is gone
    # because `model.NONE_WORD` makes `None` the word 0, which is the
    # representation rather than an approximation, and `fold_literal_expr`
    # folds it: `bugs/FORMAL_none_is_not_a_literal.md` is closed and the
    # message it named is no longer emitted by anything. A cause row whose
    # marker matches no live message is a cause that blocks nothing, which is
    # indistinguishable from a cause nothing is blocked by.
    ("a class-level default that is not a value this build can materialize",
     (("is not a value this build can materialize",),)),
    # A String method that returns a SHORTER string. `formal/model.py:2602`
    # refuses `strip`/`rstrip`/`upper`/`replace` for one reason: on a bare
    # `char *` the result means writing a terminator over the receiver's
    # bytes, and a string literal's bytes are in a read+execute `__TEXT`
    # section. 1 file (`mlir.py`), in-file, both architectures, and named in
    # `bugs/FORMAL_string_value_model.md`, which is why it gets a row rather
    # than staying in the bucket: the doc says `lstrip` is the one method that
    # does not write, which is the fix's shape.
    ("a String method that returns a SHORTER string writes the receiver's bytes",
     (("returns a SHORTER string",),)),
    # A one-field struct's mutating method, where the RECEIVER is the struct, so
    # the callee hands the receiver back and the caller has to store it. One
    # value-model fact with three wordings: a formal value is one 64-bit word,
    # and it is already carrying the receiver. 0 files measured at the time of
    # writing (the refusal is newer than the last sweep), and the fix for each
    # wording is named in the message — the row is here so a swept file that
    # lands on it reads as this construct rather than as `other refusal`.
    ("a one-field struct's mutator has no convention to write its answer back",
     (("mutating method",),)),
)

def _check_cause_shape():
    """Every cause is (label, alternatives) and every alternative is a TUPLE.

    Written because this table already carried the mistake once, and the
    failure mode is the quiet kind: an alternative written `(("marker",))` with
    one string in it is still an iterable, so `all(marker in msg for marker in
    alternatives)` tests the message for each CHARACTER of the string and every
    ordinary English message contains all of them. Nothing raises. The cause
    simply collects every message nobody earlier cause claimed — 71 files under
    a name about nested frames, with an example that has nothing to do with
    either — and the only symptom is a number that is wrong.
    """
    for label, alternatives in CAUSES:
        if not isinstance(label, str) or not label:
            raise AssertionError(f"cause label is not a string: {label!r}")
        if not isinstance(alternatives, tuple) or not alternatives:
            raise AssertionError(
                f"{label!r}: alternatives must be a non-empty TUPLE of tuples, "
                f"got {type(alternatives).__name__} — a bare string here is "
                f"iterated CHARACTER by character and matches nearly "
                f"everything")
        for alt in alternatives:
            if not isinstance(alt, tuple) or not alt:
                raise AssertionError(
                    f"{label!r}: each alternative must be a non-empty TUPLE of "
                    f"marker strings, got {type(alt).__name__}")
            for marker in alt:
                if not isinstance(marker, str) or not marker:
                    raise AssertionError(
                        f"{label!r}: marker must be a non-empty string, got "
                        f"{marker!r}")


_check_cause_shape()


# The name inside `'…' has no home` / `is a field access through` / … — the
# quoted identifier the refusal is about, which is often the fastest way to see
# that a cause is really several (`'List'` 36 against `'DType'` 4 says the
# subscript and the member-expression spellings are one row and two problems).
_REFUSED_NAME_RE = re.compile(r"'([A-Za-z_]\w*)'")

# The cause whose refusal is about a MODULE's boundary rather than about a
# construct in the file that was swept. It is named here rather than tested for,
# because the `uses:` column is computed for every cause (it is the same three
# lines) and this is the one where reading it changes what to do next: the fix
# named by the message is a project (monomorphization), and the number beside
# it says the row is not that project's priority.
CAUSE_NO_BOUNDARY_SYMBOL = "module exports no public functions"

DEFAULT_MIN = 1


def classify_message(msg):
    """The cause label for one terminal message, or `"other refusal"`.

    ANY alternative matching is enough; every marker WITHIN an alternative must
    be present. See the module docstring for what happens when either half is
    the other.
    """
    for label, alternatives in CAUSES:
        for markers in alternatives:
            if all(marker in msg for marker in markers):
                return label
    return "other refusal"


# ── `uses:` — of the files a refusing module blocks, how many name anything it
# declares. See the module docstring for why this is the first number to read
# for a cause about a module's boundary.

_decl_cache: dict = {}
_src_cache: dict = {}


def _declared_names(path: str):
    """The top-level names `path` declares, or None if it cannot be read/parsed.

    From `reflect.export_exclusions`, which is the ONE export rule:
    `formal/build.py`'s `no_public_api_reason` builds its message out of the
    same table, so the names searched for below are exactly the names the
    refusal is about and cannot drift from it. Its keys are the declarations
    the rule EXCLUDED — which is the whole population for a cause whose message
    is "this module exports nothing".
    """
    if path in _decl_cache:
        return _decl_cache[path]
    out = None
    try:
        import reflect
        with open(path, encoding="utf-8", errors="replace") as f:
            out = set(reflect.export_exclusions(f.read()))
    except Exception:                                   # noqa: BLE001
        out = None
    _decl_cache[path] = out
    return out


def _source(path: str):
    if path not in _src_cache:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                _src_cache[path] = f.read()
        except OSError:
            _src_cache[path] = ""
    return _src_cache[path]


_index: dict = {}


def _source_index():
    """`{basename: [paths]}` over this repository and the stdlib, built once.

    The chain in a sweep line names a refusing module by BASENAME
    (`binary_heap.mojo`) and never says where it is, so resolving it from the
    blocked file's own search roots — the obvious thing — works only when the
    module happens to sit in a directory that file can see. `dtype.mojo` is at
    `std/dtype/dtype.mojo` and `binary_heap.mojo` at
    `std/collections/binary_heap.mojo`, so neither resolves from a file under
    `std/sys/`, and the column silently reported "source not resolvable" for
    the two largest rows in the table. An index over the two trees that
    contain every source the sweep can compile is exact instead.

    A basename with more than one match resolves to NOTHING rather than to the
    first one: several stdlib packages have an `__init__.mojo`, and a count
    computed from the wrong one is a number nobody can check.
    """
    global _index
    if _index:
        return _index
    roots = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    try:
        import module_loader
        if module_loader.STDLIB_PATH:
            roots.append(os.path.abspath(module_loader.STDLIB_PATH))
    except Exception:                                   # noqa: BLE001
        pass
    skip = {".git", "__pycache__", "build", ".tmp", "node_modules"}
    idx: dict = collections.defaultdict(list)
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for name in filenames:
                if name.endswith((".mojo", ".py")):
                    idx[name].append(os.path.join(dirpath, name))
    _index = dict(idx)
    return _index


def _resolve_refuser(refuser: str, blocked_file: str):
    """The source path of a refusing module named by BASENAME in the chain, or
    None when it is absent or ambiguous. See `_source_index`."""
    hits = _source_index().get(os.path.basename(refuser))
    if hits and len(hits) == 1:
        return hits[0]
    return None


def _uses_table(rows_for_label):
    """`[(module, source, blocks, uses, declared_names)]`, biggest first.

    One entry per refusing module, `uses` counting the blocked files that
    contain any name the module declares as a WHOLE WORD. A word boundary and
    not a substring, because `BinaryHeap` inside `BinaryHeapX` is not a use of
    it; and the count is over the blocked files, never over the module itself,
    so `uses <= blocks` is an invariant a reader can check. `source` is None
    when the basename is absent or ambiguous and `uses` is then 0 — which the
    printed note says, so a 0 can never be read as a measurement.
    """
    groups = collections.defaultdict(list)
    for path, refuser in rows_for_label:
        groups[refuser].append(path)
    out = []
    for refuser, files in groups.items():
        src = _resolve_refuser(refuser, files[0])
        declared = sorted(_declared_names(src) or ()) if src else []
        uses = 0
        if declared:
            pat = re.compile(r"\b(?:%s)\b" % "|".join(
                re.escape(n) for n in declared))
            uses = sum(1 for f in files if pat.search(_source(f)))
        out.append((refuser, src, len(files), uses, declared))
    out.sort(key=lambda r: (-r[2], r[0]))
    return out


def rank(log_path):
    """`[{cause, files, in_file, refused_in, example, text}]`, biggest first."""
    rows = []
    with open(log_path, errors="replace") as f:
        for raw in f:
            m = LINE_RE.match(raw.rstrip("\n"))
            if m and m.group("cls") in ("CODEGEN", "CODEGEN/DEPENDENCY"):
                rows.append((m.group("cls"), m.group("path"), m.group("detail")))

    blocked = collections.Counter()
    in_file = collections.Counter()
    where = collections.defaultdict(collections.Counter)
    refused_names = collections.defaultdict(collections.Counter)
    examples = {}
    # (path, refuser) per cause, for the `uses:` column — the same two facts
    # `where` counts, kept as rows because the column needs the file each
    # refusal was reported against, not just the count.
    per_cause = collections.defaultdict(list)
    for cls, path, detail in rows:
        hops, term = FS._split_chain(detail)
        refuser = FS._refuser(term)
        msg = FS._terminal_reason(term).strip()
        label = classify_message(msg)
        blocked[label] += 1
        if cls == "CODEGEN":
            in_file[label] += 1
        # Where the refusal really came from, which is NOT the file the sweep
        # swept: for a dependency that is the module at the end of the chain,
        # and the distinction is the whole reason the class exists.
        src = refuser or (hops[-1] if hops else "(this file)")
        where[label][src] += 1
        if src != "(this file)":
            per_cause[label].append((path, src))
        named = _REFUSED_NAME_RE.search(msg)
        if named:
            refused_names[label][named.group(1)] += 1
        if label not in examples:
            examples[label] = (path, msg)

    out = []
    for label, n in blocked.most_common():
        path, msg = examples[label]
        out.append({
            "cause": label,
            "files": n,
            "in_file": in_file[label],
            "refused_in": where[label].most_common(),
            "refused_names": refused_names[label].most_common(),
            "uses": _uses_table(per_cause[label]),
            "example": path,
            "text": msg,
        })
    return out, sum(blocked.values())


# ── the HOST row: `not-answerable/host-import`, ranked by the MODULE ─────────
#
# The cause table above is keyed on what a fix would have to CHANGE, and its
# largest class in the 2026-10-02 sweep was 285 codegen lines against 241
# host-import ones. It cannot rank the host row at all: a host-import line is
# not a refusal about a construct, it is a refusal about a MODULE, so the
# question "what would a person do next" is "which module" and the whole
# ranking is by module.
#
# THE SAME `uses:` DISCIPLINE, and it matters MORE here than there. A host
# import blocks a file through its import CLOSURE exactly as a dylib with no
# boundary symbol does (`formal/build.py` builds a dylib for every module in a
# file's eager closure), so `gimple_codegen.py imports 'zlib'` blocks every
# file that imports `gimple_codegen` whether or not any of them says `zlib`.
# `FILES BLOCKED` therefore has the same upper-bound property the cause table's
# does, and the column beside it is the one that decides whether a row is WORK
# or WAITING.
#
# THE SPELLING IS COUNTED, NOT THE WORD. The codegen column searches for a
# whole word because the names it looks for are `BinaryHeap` and `slice`; the
# names here are `copy`, `types`, `signal`, `inspect` and `html`, which are
# ordinary English words that appear in prose, in comments and in the bodies of
# functions that have nothing to do with the module. A bare word search would
# report `copy` as used by five files when it is used by none. So a file counts
# as USING a host module when it contains `mod.NAME` with `NAME` one the module
# declares, or a `from mod[.sub] import …` line binding one — which are the two
# spellings a use can have.
#
# THE NAMES COME FROM CPYTHON'S OWN SOURCE, parsed, not from a list here. A
# list of "the names of `tempfile`" written in this file would be correct for
# exactly as long as CPython does not change it, and it would be wrong in the
# worst direction: the count that says "four names to write" would keep saying
# four while the four had changed. `__all__` wins over the parsed bindings where
# CPython defines it, because `__all__` is what CPython itself publishes.
#
# TIER AND MODEL ARE READ, NEVER COPIED. `formal/imports.py` owns the split
# between a fact about the target and a gap with an owner, and it publishes it
# through `host_module_tier`; the model column is `formal/hostmods/` walked for
# real. A copy of either would be a second list that rots the day a module is
# written — which is the ordinary way this row gets smaller.

_host_decl_cache: dict = {}


def _stdlib_dir():
    """CPython's own standard library directory, or None."""
    try:
        import sysconfig
        path = sysconfig.get_paths().get("stdlib")
    except Exception:                                   # noqa: BLE001
        return None
    return path if path and os.path.isdir(path) else None


def _host_source_path(name: str):
    """`name`'s source file in CPython's stdlib, or None when it has none.

    None is the honest answer for a module that is not Python source at all —
    `zlib` and `_socket` are built into the interpreter, `sys` is frozen — and a
    row whose names cannot be read says so rather than reporting a measured 0.
    """
    root = _stdlib_dir()
    if root is None:
        return None
    parts = name.split(".")
    for cand in (os.path.join(root, *parts) + ".py",
                 os.path.join(root, *parts, "__init__.py")):
        if os.path.isfile(cand):
            return cand
    return None


def _host_declared_names(name: str):
    """The names a caller can bind from the host module `name`, or None.

    `__all__` where CPython defines it as a literal list, else every top-level
    binding the source makes that does not begin with an underscore. None means
    the names could not be read, which the printed row says is not a count of 0.
    """
    if name in _host_decl_cache:
        return _host_decl_cache[name]
    out = None
    path = _host_source_path(name)
    if path is not None:
        try:
            import ast
            with open(path, encoding="utf-8", errors="replace") as f:
                tree = ast.parse(f.read(), filename=path)
            names = set()
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            names.add(tgt.id)
                elif isinstance(node, ast.AnnAssign):
                    if isinstance(node.target, ast.Name):
                        names.add(node.target.id)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        names.add(alias.asname or alias.name.split(".")[0])
            if "__all__" in names:
                exported = None
                for node in tree.body:
                    if isinstance(node, ast.Assign) and any(
                            isinstance(t, ast.Name) and t.id == "__all__"
                            for t in node.targets):
                        try:
                            exported = list(ast.literal_eval(node.value))
                        except Exception:               # noqa: BLE001
                            exported = None
                if exported and all(isinstance(e, str) for e in exported):
                    names = set(exported)
            out = sorted(n for n in names
                         if n and not n.startswith("_") and n != "__all__")
        except Exception:                               # noqa: BLE001
            out = None
    _host_decl_cache[name] = out
    return out


def _host_model_source(name: str):
    """The `formal/hostmods` file that answers `name`, or None."""
    root = os.path.join(REPO, "formal", "hostmods")
    for cand in (os.path.join(root, *name.split(".")) + ".mojo",
                 os.path.join(root, *name.split("."), "__init__.mojo")):
        if os.path.isfile(cand):
            return os.path.relpath(cand, REPO)
    return None


def _host_tier(name: str):
    """`formal/imports.py`'s own answer, read through its published accessor."""
    try:
        from formal.imports import host_module_tier
        return host_module_tier(name)
    except Exception:                                   # noqa: BLE001
        return ""


def _host_use_names(path: str, module: str, declared):
    """The declared names of `module` this file binds, as a set.

    The two spellings a use has, and nothing else: `mod.NAME`, and a
    `from mod[.sub] import …` line binding `NAME`. Empty means "not measured"
    only when `declared` is empty, which the caller reports as such.
    """
    src = _source(path)
    if not src:
        return set()
    mod = re.escape(module)
    hits = set()
    for n in declared:
        if re.search(rf"(?<![\w.]){mod}\s*\.\s*{re.escape(n)}\b", src):
            hits.add(n)
    for m in re.finditer(rf"^[ \t]*from[ \t]+{mod}(?:\.\w+)*[ \t]+import[ \t]+"
                         rf"([^\n#]+)", src, re.M):
        for word in m.group(1).split(","):
            bound = word.strip().split(" as ")[-1].strip().strip("()")
            if bound in declared:
                hits.add(bound)
    return hits


def _host_modules_in(detail: str):
    """The host module name(s) one `not-answerable/host-import` line is about.

    Read with `formal_sweep.py`'s OWN chain-peeling and import regex, so the
    module this tool names is the module that tool's classifier named: a second
    reader of the same message is a second opinion about the same verdict, and
    two opinions is one too many. The two wordings both carry `imports '…'`, and
    the SEVERAL-imports shape carries one per name — so it is handled as a list
    rather than taking the last, for the reason
    `formal/imports.py::unresolvable_import_errors`'s docstring records.
    """
    _hops, term = FS._split_chain(detail)
    term = FS._terminal_reason(term)
    multi = FS._MULTI_IMPORT_RE.search(term)
    if multi:
        names = FS._IMPORT_RE.findall(multi.group("body"))
    else:
        names = FS._IMPORT_RE.findall(term)
    return names[-1:] if names else []


def host_rank(log_path):
    """`[{module, files, uses, names, tier, model, unclassified}]`, biggest first.

    `files` counts a file once per module it is blocked by, so a file importing
    two unbuildable host modules is in two rows — which is the truth of the
    diagnostic, which names both (`formal/imports.py`'s `unresolvable_import_
    errors`) — and `total_files` beside the table says how many DISTINCT files
    the rows cover, so the two can be told apart rather than added.
    """
    per_module = collections.defaultdict(list)
    lines = 0
    files_all = set()
    with open(log_path, errors="replace") as f:
        for raw in f:
            m = LINE_RE.match(raw.rstrip("\n"))
            if not m or m.group("cls").lower() != FS.CLASS_HOST:
                continue
            lines += 1
            path = m.group("path")
            files_all.add(path)
            for mod in _host_modules_in(m.group("detail")):
                per_module[mod].append(path)
    out = []
    for mod, files in per_module.items():
        declared = _host_declared_names(mod)
        per_file = collections.defaultdict(set)
        for f in files:
            per_file[f] |= _host_use_names(f, mod, declared or ())
        uses = sum(1 for f, names in per_file.items() if names)
        names = collections.Counter()
        for hit in per_file.values():
            for n in hit:
                names[n] += 1
        out.append({
            "module": mod,
            "files": len(files),
            "uses": uses,
            "names": names.most_common(8),
            "declared_known": declared is not None,
            "declared": declared or (),
            "tier": _host_tier(mod),
            "model": _host_model_source(mod),
            # IN NO TIER is only a DEFECT when there is no model: a module that
            # has been WRITTEN is in no tier by design (`HOST_MODELLED`'s rule
            # is "a name LEAVES here by being WRITTEN", `HOST_ADMITTED`'s is "a
            # name is here iff it has a source"), and its import resolves before
            # either set is consulted. `os`, `sys` and `re` are in no tier for
            # that reason and are not mis-diagnosed; `datetime` and `builtins`
            # are in no tier because nobody classified them, and every file
            # that wants one is told its import "is not a stdlib or sibling
            # module, and no such file exists", which is false.
            "untiered": not _host_tier(mod) and not _host_model_source(mod),
        })
    out.sort(key=lambda r: (-r["files"], r["module"]))
    return out, lines, len(files_all)


def print_host_table(table, minimum, lines=0, files_all=0):
    print(f"{'files':>5} {'uses':>5}  {'tier':<11} {'model':<26} host module")
    for r in table:
        if r["files"] < minimum:
            continue
        # A module with a source is WRITTEN, which is a third state and not a
        # missing one: it is in neither tier because `HOST_MODELLED`'s rule is
        # "a name LEAVES here by being WRITTEN" and `HOST_ADMITTED`'s is "a name
        # is here iff it has a source", and its import resolves before either
        # set is consulted. Printing it as UNTIERED would report `os` and `sys`
        # as mis-diagnosed.
        tier = r["tier"] or ("written" if r["model"] else "UNTIERED")
        model = r["model"] or "—"
        uses = r["uses"] if r["declared_known"] else "?"
        print(f"{r['files']:>5} {str(uses):>5}  {tier:<11} {model:<26} "
              f"{r['module']}")
        if not r["declared_known"]:
            print(f"        uses:        NOT MEASURED: {r['module']} has no "
                  f"source in this interpreter's stdlib (it is built in or "
                  f"frozen), so nothing here can be counted")
        elif r["uses"] == 0:
            print(f"        uses:        0 — every blocked file names nothing "
                  f"{r['module']} declares, so the row is import CLOSURE and "
                  f"not {r['files']} files of work")
        elif r["uses"] < r["files"]:
            print(f"        uses:        {r['uses']} of {r['files']}; the other "
                  f"{r['files'] - r['uses']} name nothing it declares, so they "
                  f"are closure")
        if r["names"]:
            print(f"        names:       "
                  + ", ".join(f"{k} x{v}" for k, v in r["names"]))
        if r["untiered"]:
            print(f"        UNTIERED:    {r['module']} is in NEITHER "
                  f"formal/imports.py tier, so its refusal reads "
                  f"\"not a stdlib or sibling module, and no such file "
                  f"exists\" — a statement about module RESOLUTION that is "
                  f"false of a CPython standard-library module")
    shown = [r for r in table if r["files"] >= minimum]
    pairs = sum(r["files"] for r in shown)
    print(f"\n{pairs} blocked file x module pairs over {files_all} files, "
          f"accounting for {lines} host-import lines, in {len(shown)} "
          f"module(s) of {len(table)}")
    print("FILES BLOCKED IS AN UPPER BOUND here too, and for the same reason: "
          "a file's\nterminal cause is the first refusal its build walk "
          "reaches, and a host import blocks\nevery importer of its importers. "
          "The `uses` column is the number that says\nwhether a row is WORK or "
          "a row waiting on one module.")
    print("`tier` is read from formal/imports.py::host_module_tier and `model` "
          "from formal/hostmods/;\nneither is copied here. 'unreachable' is a "
          "fact about the target, 'modelled' is a gap\nwith an owner, and "
          "'admitted' is a module that answers under a declared contract.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", help="a formal_sweep.py log (stdout+stderr)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable, one object per cause")
    ap.add_argument("--host", action="store_true",
                    help="rank the not-answerable/host-import row by the "
                         "MODULE named, instead of ranking codegen causes")
    ap.add_argument("--min", type=int, default=DEFAULT_MIN, dest="minimum",
                    help=f"only causes blocking at least N files "
                         f"(default {DEFAULT_MIN})")
    args = ap.parse_args()

    if args.host:
        table, lines, files_all = host_rank(args.log)
        if args.json:
            json.dump({"modules": table, "lines": lines,
                       "files": files_all}, sys.stdout, indent=1)
            print()
        else:
            print_host_table(table, args.minimum, lines, files_all)
        return 0

    table, total = rank(args.log)
    shown = [r for r in table if r["files"] >= args.minimum]
    if args.json:
        json.dump(shown, sys.stdout, indent=1)
        print()
    else:
        print(f"{'files':>5} {'in-file':>7}  cause")
        for r in shown:
            print(f"{r['files']:>5} {r['in_file']:>7}  {r['cause']}")
            print(f"        refused in: "
                  f"{', '.join(f'{k} x{v}' for k, v in r['refused_in'])}")
            if r["refused_names"]:
                print("        names:      "
                      + ", ".join(f"{k} x{v}"
                                  for k, v in r["refused_names"][:8]))
            for refuser, src, blocks, uses, declared in r["uses"]:
                if src is None:
                    note = ("NOT MEASURED: the chain names this module by "
                            "basename only and that basename is absent or "
                            "ambiguous in this tree")
                elif not declared:
                    note = ("measured 0, and it cannot be otherwise: the "
                            "module declares no name the export rule could "
                            "exclude")
                elif uses == 0:
                    note = ("the refusal is about the import CLOSURE, not "
                            "about these files — see the module docstring")
                elif uses == blocks:
                    note = "every blocked file uses it, so the row is work"
                else:
                    note = (f"{blocks - uses} of the {blocks} name nothing it "
                            f"declares; the rest of the row is closure")
                print(f"        uses:        "
                      f"{'not measured' if src is None else uses} "
                      f"of {blocks} blocked by {refuser} name anything it "
                      f"declares"
                      + (f" ({', '.join(declared[:6])})" if declared else "")
                      + f"  [{note}]")
            print(f"        example:    {r['example']}")
        shown_files = sum(r["files"] for r in shown)
        print(f"\n{shown_files} of {total} codegen/dependency lines "
              f"accounted for, in {len(shown)} cause(s) of "
              f"{len(table)}")
        print("FILES BLOCKED IS AN UPPER BOUND: a file's terminal cause is the "
              "first refusal reached,\nso fixing one usually moves it to the "
              "next. Measure a cause's real value by\nre-sweeping the files it "
              "blocks — the census is "
              "bugs/FORMAL_sweep_work_map_2026-09-30_r2.md, which replaced "
              "§3 of the 2026-09-30 original.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
