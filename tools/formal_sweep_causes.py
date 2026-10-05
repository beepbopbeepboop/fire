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
under either probe (`“FORMAL_dylib_export_gate_ceiling: the 38-file row is not 38 problems”`).

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
import ast
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
    # An ELEMENT of a value that is not a container, and the row that makes the
    # SOURCE-PROVEN half of the container-operand family visible: before it,
    # every message from `scalar_container_base_refusal` — a literal base, or a
    # type tag — fell into `other refusal`, which is the outcome this table
    # exists to prevent.  One marker for the two shapes is deliberate: they are
    # one defect, a container lowering reading eight bytes at offset 0 of its
    # base and calling that a COUNT, and they are one defect because
    # `model.scalar_container_base_evidence` decides both and the two emitters
    # ask it through one `_refuse_scalar_container_operand`.  The marker is the
    # clause they SHARE rather than the one they open with, because every
    # message in the family opens with the same clause and a broad marker here
    # would collect the bare-name and slot rows as well.
    ("element of a value that is not a container",
     (("carries no count at offset 0",),)),
    # THE FRAME SLOT, its own row and its own fix, and the marker is the clause
    # only THIS base's message carries.  It is not the scalar row because the two
    # are different representations with different next steps — the row below is
    # "annotate it or bind it to a container", and this one is "a subscript of a
    # struct on this path is `__getitem__`" — and because lumping them would put
    # every finding in one bucket whose advice is wrong for half of them.  The
    # marker is deliberately NOT the opening clause every message in this family
    # shares ("asks for a container element"), and it is deliberately the LONGER
    # of the two that could match: the scalar row's "is a struct field declared
    # to hold" is a prefix of it, so whichever order the two are declared in,
    # the one that asks for more of the message has to come first or it is
    # shadowed.  `tools/formal_sweep.py`'s `_REFUSAL_FAMILIES` puts it there.
    ("container operation on a frame slot",
     (("declared to hold a FRAME",),)),
    # ABOVE the two rows below it, and for a reason that is a fact about the
    # messages rather than about this construct: they are all one family — a
    # representation the target does not have — and the broad ones end with a
    # sentence the specific ones also contain.
    #
    # **THE LABEL AND THE DOC CHANGED ON 2026-10-04, and both were wrong.** The
    # row was "`None` and a value are one word, with no tag", which said the
    # representation does not exist; it does. `formal/model.py`'s
    # `optional_none_word` gives `None` a word the payload's type cannot
    # produce — 0 for every reference-shaped payload, 2 for a `Bool`, `1 << w`
    # for a narrow integer — and `Some(0)` and `None` are no longer the same
    # word (measured before: `var z: Optional[Int] = 0; if z is None:` printed
    # the empty branch on both architectures). What is left in this row is the
    # PAYLOAD TYPES with no niche at all — `Int`, `Int64`, `UInt`, `UInt64`,
    # `Float64`, an unstated payload, a struct of another module — which need
    # the tagged TWO-WORD value, plus the receivers that state no type at all.
    # Its own doc moved with it.
    #
    # TWO markers, because there are now TWO live sentences and one of them
    # quotes the type name: `UNWRAP_METHODS` says "is an Optional unwrap" (the
    # receiver's type is not stated) and `optional_unwrap_refusal` / 
    # `optional_no_niche_refusal` say "is an `Optional[...]`" (it is stated, and
    # names the payload). A row matching only the first would have gone quiet
    # on the second while still reading as one that blocks something — the
    # "a cause whose marker matches no live message is a cause that blocks
    # nothing" failure this file's own module docstring names.
    ("Optional unwrap: the payload type has no niche, or the receiver states none",
     (("is an Optional unwrap",),
      ("is an `Optional` unwrap",),
      ("is an `Optional[",))),
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
    #
    # **AND since 2026-10-04 the row above is the odd one out in a way this
    # comment has to record.** A from-import whose name the module publishes as a
    # FUNCTION is no longer refused as "a module-level name of another module":
    # it is a call through a VALUE, which is what the dotted spelling has said
    # since 2026-10-04, and its message carries the same clause — so it lands
    # HERE rather than above (`model.imported_function_as_a_value_refusal`,
    # `test_formal_module_attr.py`'s `the IMPORTED spelling of a call through a
    # value says the same`). That is the classification being made more precise
    # rather than the row being widened: both spellings now name one construct.
    # **Measured on the 2026-10-04 arm64 log: no file moves**, because the one
    # file the bare row holds is `std/time/__init__.mojo`'s
    # `time.mojo: 'CompilationTarget'`, and a TYPE is pre-empted by
    # `model.is_type_name` before either arm — so the row above is 1 file of a
    # TYPE and this row is 30 of the constructs it names.
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
    # (`FORMAL_debug_assert_bracket_has_no_lowering`).
    #
    # Above `callee has no definition` deliberately. The two messages are about
    # the same callee and share no substring — that one says "a name with no
    # definition in hand", this one "calls a name this unit does not compile" —
    # so today the order is documentation. It is pinned by
    # `test_refusal_taxonomy.py` so it stays that way in BOTH directions.
    ("a bracketed specialization of a callee this unit does not compile",
     (("so the brackets cannot be bound",),)),
    # A CALL to a name the DEFINING module does not export, which is the largest
    # row in the corpus and had NO row at all until 2026-10-04: 170 of the 710
    # files on the b10 sweep, 55% of every codegen finding in the tree, all of
    # them carrying ONE sentence from `formal/model.py::imported_callee_refusal`
    # — and `other refusal`, the bucket this table's own docstring defines as
    # "nobody has looked", was how the ranking reported them.
    #
    # It is the row the per-edge export gate (`formal/imports.py::library_free_edges`)
    # emptied INTO: at `-9` those files were 125 on `module exports no public
    # functions` and 43 on `Optional unwrap`, both NAMED; fixing the gate in front
    # of them moved them one refusal further on, to a refusal this table could not
    # name. So the fix that made the backend build more files also made the
    # instrument blind, which is the shape of that defect in general — the same one
    # `…_b9.md` §5.1 fixed for the `with`.
    #
    # THE MARKER IS THE FACT, NOT THE ADVICE. Two clauses of the message are
    # load-bearing and stable: the call "has to bind a symbol `M` exports", and
    # "That module does not export it". The sentence that USED to follow them —
    # "spell it as `name[<a type>](…)`" — is advice, and `work/formal19-1`
    # deletes it because it is wrong about correct Mojo (a bare template call is
    # the spelling the stdlib uses). Keying on that would have taken 170 files
    # silently back to `other refusal` the day a branch nobody is waiting for
    # landed, which is the failure the comments above this table warn about twice.
    ("a call to a name the defining module does not export",
     (("does not export it",),)),
    # ── a call through a VALUE: three shapes, three rows, and the distinction
    #    is which DECLARATION is missing. They used to be one refusal, so all
    #    three sat in `other refusal`, which is the bucket that means nobody has
    #    looked. Above the `is passed to` pair below because each of these
    #    messages contains "a call through a VALUE" and two of them contain a
    #    clause that pair would otherwise claim; pinned in both directions by
    #    `test_refusal_taxonomy.py`'s samples.
    #
    # The construct LOWERS when there is nothing to read: a function value is a
    # code address, and `f[w, h](x)` through a word passes the bracket as
    # leading arguments
    # (`std/algorithm/backend/tile.mojo`'s `workgroup_function[tile_size]`).
    # These three are the shapes with no declaration in hand, and each one says
    # what the reader can write instead.
    ("a call through a value whose declared type cannot hold one",
     (("a word that is not a code address is nothing to branch through",),)),
    ("a function passed where the callee declares something else",
     (("is passed to", "read as a value"),)),
    ("a bracketed callee through a value, which this build cannot read",
     (("is a bracketed call through a VALUE",),)),
    ("a keyword argument in a call through a value",
     (("no declaration to bind it by NAME",),)),
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
    # The OTHER `print` refusal, and it is a DIFFERENT question rather than a
    # second wording of the row above: the argument's KIND is known (it is a
    # word, and a word prints as a number), and what is wrong is that the word is
    # not a value at all — it is the leftover of a callee that returns nothing,
    # where CPython prints `None`
    # (`bugs/FORMAL_a_function_with_no_return_yields_a_word_where_cpython_
    # yields_None.md`). It needs its own row because a file refused here is
    # refused by a DECISION with a remedy (`return` something, or do not use the
    # callee's value), which is what `other refusal` — the bucket this table
    # exists to empty — cannot say, and because it will not be confused with the
    # kind-unknown row: the two messages share no clause, which is why both
    # markers are listed rather than one borrowed from the other.
    #
    # The markers are the FACT and the CONSTRUCT, and both are stated in
    # `formal/model.py::returnless_value_refusal`'s own f-string, which is where
    # `test_refusal_taxonomy.py`'s sample for this row is cut from.
    ("a printed value that is not a value: the callee returns nothing",
     (("CPython evaluates that call to `None`",),
      ("is asked to render the value of",))),
    # A REPETITION whose count this path cannot read at compile time. It is its
    # own row and not `other refusal` for the reason the `==` row above gives:
    # `xs * n` is a construct this backend now LOWERS (both architectures, a
    # copy loop and a count word — `test_formal_run.py`'s `REPEAT_CASES`), and
    # the one thing it will not do is guess a count, so a file refused here is
    # refused by a decision with a stated remedy. It needs a marker because
    # without one every file written as `[0.0] * (m * k)` — which is how a
    # GEMM allocates its buffers, and `test_llm/dumb_gemm.mojo` is that file —
    # lands in the unclassified bucket.
    ("a repetition whose count this path cannot read",
     (("is a REPETITION",),)),
    ("len() of a value that has no length",
     (("is len() of a value classified as",),)),
    # A `with` whose CONTEXT this build cannot type. `formal/model.py`'s
    # `refuse_unlowerable_with` names the protocol it cannot honour, and one of
    # its three arms is "the expression is not a construction of a struct this
    # image compiles" — which is where `with open(path, "r") as f:` lands, once
    # per file, and `with open(` is in 192 of this repository's own files.
    #
    # It needs a row because it was in `other refusal`, and this row's marker is
    # the clause only this message carries (`refuse_unlowerable_with`'s other
    # two arms are a struct that is not framed and a struct that declares no
    # `__enter__`, and both of those sentences are about a type this build DOES
    # know). Measured 2026-10-03 on the b9 sweep: 20 files at the `module_
    # loader.py` chain alone, and 47 of the corpus's classified files contain
    # the `with` this message refuses — the upper bound, since most of them are
    # refused earlier for something else.
    ("a `with` over a value this build cannot type",
     (("is CPython's CONTEXT-MANAGER PROTOCOL",),)),
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
    # A `try`'s HANDLER ARM with a body, and the one row in this table whose
    # refusal is CORRECT rather than a gap — so its number is a census, not a
    # target. `formal` has no exception unwinder: a `raise` flushes the
    # enclosing `finally` clauses and exits, so no edge runs from a raise site
    # into an arm, and every statement in the arm would be missing from the
    # program that runs. It is here because the dylib-module-body row's removal
    # (2026-10-03) made 5 files report it for the first time and they landed in
    # `other refusal`, which is the place a table like this exists to keep them
    # out of: "refused on purpose" and "nobody has looked" are different
    # answers for a reader deciding what to do next. Keyed on the clause only
    # this message carries.
    ("a handler arm with a body (no unwinder to emit it into)",
     (("is a handler arm with a body this path cannot put in the image",),)),
    # The SAME missing edge, seen from the raise site rather than from the arm,
    # and it is a second row rather than a wider marker on the one above because
    # the two messages describe different programs: that one is an arm whose
    # BODY would be missing, this one is a `try` whose SUCCESSOR would be. The
    # shape is `except: pass` around a call that raises — the arm loses nothing
    # by being dropped (which is why that row does not fire) and the control
    # flow after the `try` loses everything, because the raise ends the process
    # where CPython runs the arm and continues. Landed 2026-10-05
    # (`formal/model.py`'s `uncatchable_raise` / `refuse_uncatchable_raise`).
    #
    # Keyed on a clause only THIS message carries, for the reason the row above
    # gives: both messages say "no edge runs from a raise site into an arm", so
    # a marker on that shared clause would swallow this row's files into the one
    # above and make a census read as a target.
    #
    # **Cost: zero files, measured.** Asking the question over this repository's
    # 479 `.py`/`.mojo` files and the stdlib's 252 `.mojo` takes 43 files, and
    # every one of the 43 is already refused for another reason on this tree
    # (25 of them by an import: `fire_compiler`, `formal.build`, `collections`,
    # `socket`; the rest behind the row above or a module that exports nothing).
    # That is the number to re-measure if this row ever grows: a refusal that
    # takes files nothing else had is a different kind of row from this one.
    ("a `try` that can reach a raise, whose arm cannot catch it",
     (("cannot catch it, so the `try` is refused",),)),
    # `field(default_factory=F)` — the dataclass transform needs one value per
    # instance, and this path has nowhere to keep it: not module-global
    # storage, and a local in the constructor's frame dies with the
    # constructor. 2 files, in-file, both architectures.
    ("`field(default_factory=F)`: nowhere to keep a per-instance value",
     (("calls F once per instance",),)),
    # A constructor called WITH arguments, whose body is not a bare sequence
    # of `self.<field> = …` assignments. The inlining this path does can
    # store the assignments at the construction site; what it can now also do
    # is resolve a read of the RECEIVER against the block that construction
    # reserved — a method call is lifted to a real call with that address as
    # its receiver, and a one-level field read is a load at `block + 8·slot`
    # (`model.init_receiver_rewrite`). What is still refused here is a body
    # that BRANCHES or loops, binds a local, or reads the receiver in a shape
    # with no address to compute from. 2 files, in-file.
    ("a constructor body that reads `self` is not inlined",
     (("whose body this path does not inline",),)),
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
    # Re-pointed 2026-10-04, and the reason is the map's own §5.1 lesson about a
    # marker keyed on text that is going away: this one read `lowers only append,
    # close, write`, which is the model's own enumeration of the lowered method
    # names, so `List.clear` joining that table silently took every file in this
    # row back to `other refusal` — 170 files' worth of bucket, for a word list.
    # The clause below is the one that STATES the fact: the refusal exists
    # because the name is not one of the methods that ARE lowered, and that is
    # true whatever the table holds.
    ("method call on a value receiver is not one of the lowered methods",
     (("is not one of those methods of those receivers",),)),
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
    # folds it: `“FORMAL_none_is_not_a_literal: `x: T = None` is a NAME on this parser”` is closed and the
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
    # COMPOSITION, which is the missing BUFFER rather than a missing write, and
    # which had NO row until 2026-10-04: 114 of the 722 files on the b11 sweep,
    # 32% of every codegen finding in the tree, every one of them one sentence
    # from `formal/model.py::interpolated_literal_refusal` — and 94% of the
    # `other refusal` bucket, which this table's own docstring defines as "nobody
    # has looked". The row above is its sibling and says so: that one needs a
    # writable copy of the receiver's bytes, this one needs somewhere to PUT the
    # new ones.
    #
    # TWO WORDINGS, ONE MISSING THING, so two alternatives and not one AND. An
    # interpolated literal is refused at the MODULE (`refuse_interpolated_literals`,
    # over the whole body, before any emitter runs) and a binary `+`/`-` on two
    # strings is refused at the operator (`string_concat_refusal`), and the two
    # messages share no clause beyond the missing buffer — which is why they are
    # two alternatives. They are ONE row because `formal/model.py` says in both
    # messages that they are one thing: the f-string's own text calls it "the
    # same missing buffer `string_concat_refusal` names", and `LENGTH_DEPENDENT_
    # METHODS` is the third spelling of it. A queue that saw three rows would
    # read them as three projects.
    #
    # It is the largest row in the corpus with no owner, and it arrived five days
    # before this row did: the refusal landed 2026-10-03 (`9b40c019`, "an f-string
    # literal is REFUSED, not printed as its own spelling"), replacing a
    # wrong-but-exit-0 answer. That fix EMPTIED two rows behind it without fixing
    # them — the handler-arm row went 30 -> 1 with 29 files dark, and the
    # module-ATTRIBUTE row 30 -> 4 with 25 dark — which is
    # `FILES BLOCKED IS AN UPPER BOUND` arriving as a queue's blind spot rather
    # than as a caveat. See `bugs/FORMAL_string_composition_has_no_buffer.md` for
    # the measurement and what a lowering would have to be.
    #
    # THE MARKER IS THE FACT, NOT THE ADVICE. "no buffer to compose one in" is
    # what is missing; the advice that follows it in the same message ("Print the
    # parts as separate operands, or build the text with `+` once that is
    # lowered") is wrong about `print` — `print("n=", n)` inserts a separator
    # between its operands, so it is not the same text — and would be deleted by
    # the fix rather than kept by it.
    ("string composition: nothing to compose into",
     (("no buffer to compose one in",),
      ("on two strings is refused on this path",))),
    # THE TEXT ENCODING BLOCK, which was the corpus's largest row with no name in
    # it: 229 of the 236 `other refusal` findings on the 2026-10-04 b12 sweep are
    # this one sentence, all of them refused in `formal/hostmods/os/_syscalls.mojo`
    # and 0 of them naming anything that module declares. `formal/model.py` calls
    # the block "TEXT ENCODING" and it is ONE representation gap — a string is a
    # bare `char *` to BYTES and CPython's `str` is CHARACTERS — asked from four
    # different constructs, so four rows would read as four projects.
    #
    # **TWO WORDINGS, ONE GAP, and the marker for the first covers THREE of the
    # four constructs** rather than there being three markers: `len`, `find`,
    # `strstr` and a `printf` `%<width>s` / `%<width>d` conversion are all said by
    # `codepoint_refusal` and `printf_text_width_refusal` /
    # `printf_text_conversion_refusal`, and all three of those functions quote the
    # SAME clause — "is refused: on this path it would answer in BYTES where
    # CPython answers in CHARACTERS" — which is why one alternative collects them.
    # The second wording is `string_element_refusal`'s and shares no clause with
    # it.
    #
    # IT IS NOT THE COMPOSITION ROW ABOVE, and the two are deliberately not
    # merged even though both messages end by pointing at the missing buffer:
    # this row's clearing condition is stated by the model itself and is about
    # the IMAGE ("no literal with a byte >= 0x80 anywhere means no string in the
    # image can have one, so every element read is a character" —
    # `string_element_refusal`'s own docstring), while composition's is a missing
    # buffer and fires on ASCII text too. Merging them would put the 115-file
    # row's advice on a construct whose answer is "keep the text ASCII", and put
    # "keep the text ASCII" on a construct no amount of ASCII fixes.
    #
    # **AND THE FACT THAT PUT 229 FILES HERE WAS FIXED ON 2026-10-04**, which is
    # the reason this row's count is a statement about a DEFECT and not about a
    # gap: the scan that publishes a unit's non-ASCII literals was publishing
    # DOCSTRINGS, whose bytes nothing can name, so six lines of em-dash in one
    # hostmod's prose made this refusal fire over the whole corpus. That is
    # `formal/model.py::is_docstring_statement`, and
    # `bugs/FORMAL_sweep_work_map_2026-10-04_b12.md` §3.2 has the measurement.
    # The row STAYS, because the refusal is CORRECT for a real non-ASCII value —
    # `s[i]` on `"héllo"` would read a continuation byte, and `len` would answer
    # 5 where the byte count is 6 — and a queue that emptied this row by deleting
    # it would be reading a fix as a closure.
    #
    # The marker is the FACT ("would answer in BYTES where CPython answers in
    # CHARACTERS", "whose text is not ASCII"), not the advice that follows it in
    # the same message, for the reason the composition row states: a fix deletes
    # the advice.
    ("a non-ASCII string: BYTES where CPython has CHARACTERS",
     (("is refused: on this path it would answer in BYTES where CPython "
       "answers in CHARACTERS",),
      ("is refused on a string whose text is not ASCII",))),
    # A one-field struct's mutating method, where the RECEIVER is the struct, so
    # the callee has to hand the receiver back somehow. Four wordings and one
    # cause, because one convention covers the receiver and what is refused is
    # the four shapes it does not.
    #
    # **Re-pointed and renamed 2026-10-03** (`work/formal15-mutator-return-abi`).
    # The mechanism is now BY REFERENCE — the mutator receives the address of the
    # caller's one-word cell and writes the receiver back through it — which
    # removed the wording that was this cause's headline: "both changes its
    # receiver and returns a value", which is `BinaryHeap.pop()` and the 165-file
    # `binary_heap.mojo` sweep row. The old marker was the single word
    # `"mutating method"`, which matched two of the four wordings and would have
    # dropped the other two into `other refusal` silently — the failure mode this
    # module's own docstring names. Four alternatives now, one per wording.
    #
    # The old LABEL said the cause was that the answer had nowhere to go back to,
    # which is false as of that commit: it goes back through the address. What is
    # refused is the four shapes the convention does not reach, so the label says
    # that.
    ("a one-field mutator's receiver hand-off is refused",
     (("declares no return type, so the call has no value",),
      ("is not a place this path can take the address of",),
      ("is called in the same argument list that reads",),
      ("two hidden-word conventions",))),
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

#: The bucket a message lands in when no cause in `CAUSES` claims it, named here
#: because `formal_sweep.py`'s loud unclassified-shape finding — its
#: `unclassified_report`, which owns the shapes, the threshold and the sweep's
#: exit 4 — is fed this same string from this side, and two spellings of one
#: bucket would be two buckets.
UNCLASSIFIED = "other refusal"

DEFAULT_MIN = 1


def classify_message(msg: str):
    """The cause label for one terminal message, or `UNCLASSIFIED`.

    ANY alternative matching is enough; every marker WITHIN an alternative must
    be present. See the module docstring for what happens when either half is
    the other.
    """
    for label, alternatives in CAUSES:
        for markers in alternatives:
            if all(marker in msg for marker in markers):
                return label
    return UNCLASSIFIED


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
    """The source path of a refusing module, or None when absent or ambiguous.

    **Two questions, asked in that order, because they have different
    answers.** A chain that carries a `<file>: ` prefix names a FILE, and the
    basename index is exact for it. A chain that names its module in prose —
    `formal/model.py::imported_callee_refusal`, and that is the largest row in
    the corpus — names a DOTTED PATH (`std.format._utils`, `std.math`), and the
    build's own resolver answers it: `formal.imports.resolve_module_path`, the
    same call `tools/formal_chain_probe.py` makes, so there is one resolver and
    not two spelling rules.

    **A RELATIVE spelling is left unresolved on purpose.** `..fstat` and
    `.path` are relative to the file that did the importing, which is inside
    the chain and not the file the sweep swept, so answering it from
    `blocked_file` would be a guess — and this column's whole discipline is that
    an unmeasured number says so. `_refusal_module_of` therefore keeps the
    name and the path apart, and a name that cannot be resolved leaves `uses:`
    reading NOT MEASURED.

    A basename with more than one match resolves to NOTHING rather than to the
    first one (see `_source_index`): several stdlib packages have an
    `__init__.mojo`, and a count computed from the wrong one is a number nobody
    can check.
    """
    if _looks_like_a_module_name(refuser):
        found = _resolve_dotted(refuser, blocked_file)
        if found:
            return found
    hits = _source_index().get(os.path.basename(refuser))
    if hits and len(hits) == 1:
        return hits[0]
    return None


def _looks_like_a_module_name(name: str) -> bool:
    """A dotted MODULE name (`std.format._utils`, `..fstat`, `.philox`) rather
    than a file the chain already named (`binary_heap.mojo`).

    The discriminator is the extension and the separator, not the dots: half the
    basenames this tool is handed end in `.mojo`, and handing one to
    `resolve_module_path` answers with the repository root joined to its stem —
    a real path, to a file that is not the module, which is the one answer worse
    than no answer.
    """
    if not name or name.endswith((".mojo", ".py")) or os.sep in name:
        return False
    return "." in name


def _resolve_dotted(name: str, blocked_file: str):
    """`formal.imports.resolve_module_path(name, relative_to=blocked_file)`, or
    None — including when the import machinery is not importable, which is what
    a checkout without `formal/` on the path looks like from here."""
    if os.environ.get("MOJO_STDLIB"):
        return None                      # this tool never builds, never reads
    try:
        from formal.imports import resolve_module_path
    except Exception:                                   # noqa: BLE001
        return None
    try:
        return resolve_module_path(name, relative_to=blocked_file,
                                   project_root=blocked_file)
    except Exception:                                   # noqa: BLE001
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
    """`([{cause, files, in_file, refused_in, example, text}], lines, unclassified)`.

    `lines` is the total this table accounted for, and `unclassified` is
    `[(path, terminal message)]` for every row this table could not name — which
    is what `formal_sweep.py`'s loud unclassified-shape finding is fed, so that
    the alarm is ONE implementation reached from both instruments rather than a
    threshold and a printer that have to be kept in step here. Returns a third
    value because the pairs are read off the same pass over the log as the
    counts; a second pass would be a second reader of the same file.
    """
    rows = []
    with open(log_path, errors="replace") as f:
        for raw in f:
            m = LINE_RE.match(raw.rstrip("\n"))
            if m and m.group("cls") in ("CODEGEN", "CODEGEN/DEPENDENCY"):
                rows.append((m.group("cls"), m.group("path"), m.group("detail")))

    unclassified = []
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
        msg = FS._terminal_reason(term).strip()
        # The refusing module, from the chain's `<file>: ` prefix when it has
        # one and from the message's own sentence when it does not. Without the
        # second half the corpus's largest row groups under its IMPORTER (21 of
        # 22 groups on the std/{os,io,…} scope, `uses:` NOT MEASURED on every
        # one of them), which is a different module from the one the reader has
        # to open.
        refuser = FS._refuser(term) or FS.refusing_module(msg)
        label = classify_message(msg)
        blocked[label] += 1
        if label == UNCLASSIFIED:
            unclassified.append((path, msg))
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
    return out, sum(blocked.values()), unclassified


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


def _module_scope_bindings(nodes, names):
    """Every name bound at MODULE scope in `nodes`, and recursively in the bodies
    of the statements that run at import.

    A module attribute is a binding in the module's own namespace, and CPython's
    stdlib puts a real share of them inside `if`/`try`/`with` at module level:
    `types.py` binds `SimpleNamespace = type(sys.implementation)` inside a
    module-level `try:` that imports `_collections_abc`, and `types.__all__` is
    `[n for n in globals() if not n.startswith('_')]` — a COMPREHENSION, which
    `ast.literal_eval` cannot answer, so the `__all__` path does not fire for
    that module and the top-level scan is all there was.

    Scanning `tree.body` alone therefore reported `types` as declaring six names
    and the ranking printed `uses: 0 — every blocked file names nothing types
    declares, so the row is import CLOSURE` while **22 blocked files spell
    `types.SimpleNamespace` and 9 spell `types.ModuleType`** (`myinterpreter.py`
    alone has 22 of the former). That is the direction this tool must never be
    wrong in: it reads as "nothing to do here" and it is the largest false
    negative the `--host` table has had.

    The recursion stops at function and class bodies, and that boundary is the
    whole discipline: a `def`'s locals are not module attributes, so descending
    into one would add every local in CPython's stdlib (measured on `inspect`:
    400+ names, none of them an attribute) and a `class`'s body is a namespace
    of its own. What runs at import — `if`, `try`, `with`, `for`, `while` — is
    descended, because a name bound there IS in the module's namespace.
    """
    import ast
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            names.add(node.name if hasattr(node, "name") else "")
            continue
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.add(node.target.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.If, ast.Try, ast.With, ast.AsyncWith,
                               ast.For, ast.AsyncFor, ast.While)):
            _module_scope_bindings(node.body, names)
            # `except` handlers and `else`/`finally` are module scope too, and
            # `TryStar` (3.11+) is spelled separately from `Try` in the AST.
            _module_scope_bindings(getattr(node, "orelse", []), names)
            _module_scope_bindings(getattr(node, "finalbody", []), names)
            for h in getattr(node, "handlers", []) or ():
                _module_scope_bindings(h.body, names)


def _host_declared_names(name: str):
    """The names a caller can bind from the host module `name`, or None.

    `__all__` where CPython defines it as a literal list, else every module-scope
    binding the source makes that does not begin with an underscore. None means
    the names could not be read, which the printed row says is not a count of 0.

    **A `__all__` that is not a literal list falls through to the scan, and that
    fallback has to see module-scope bindings inside `if`/`try`/`with`** — see
    `_module_scope_bindings`, and `types.py` for the case that made it a
    function rather than a loop.
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
            _module_scope_bindings(tree.body, names)
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


def _host_mentions_module(path: str, module: str):
    """Whether `path` USES `module`, by AST. None when that cannot be told.

    The fallback for a row whose declared NAMES could not be read (`zlib`,
    `itertools`, `builtins` — built into the interpreter, so there is no source
    here to parse). `_host_use_names` asks "which of this module's names does
    this file bind", which needs the module's source; this asks the question
    that does not — "does this file spell the module AT ALL" — and **zero is a
    sound answer to it**: a file that never mentions the module cannot be using
    whatever it exports, whatever that is. That is the answer that says a row of
    N files is N files of CLOSURE, and it is the answer this row needed: 29
    files were blocked by `zlib` and not one of them spelled it.

    **AST, not a word search, and that is the whole of the discipline.** The
    corpus says `zlib` in PROSE: `mojo/middle/coro.py` writes "#
    `_crc32_str`, NOT `zlib.crc32` (stubbed self-hosted — see its doc)" and
    `mojo/middle/types.py` writes "`zlib.crc32` is not available in the
    compiled/self-hosted backend" — both in comments, both about NOT using it.
    `tools/mem_slope.py` goes further and carries `resource.getrusage(
    resource.RUSAGE_CHILDREN)` inside a STRING: the source of a child program it
    writes out, not a call it makes. A regex over raw source counts those three
    as users of two modules whose only reader is a text. Parsing reads the
    imports and the names the code actually reads, so all three answer 0 for the
    right reason.

    All four spellings a use can have, and the first is the one that subsumes
    the third:

      * `mod.NAME` anywhere — the bound name appears as a name or an attribute
        base;
      * `from mod import NAME` — the module's own name is never read, so the
        bound NAME has to be looked for instead (`from resource import
        getrusage` uses `resource` and never spells it);
      * `import mod as alias` — the alias is the name, not `mod`;
      * `import mod` whose bound name is only a `Store` (a re-export) — a
        re-export IS a use by another spelling, and this path cannot see the
        other module's read, so it is counted as a use.

    None for a `.mojo` path, because Python's own parser is not a Mojo parser
    and a zero from it would be a guess. A row with one `.mojo` file in it
    therefore reports no fallback number at all rather than one covering the
    files this could read, which is the direction this tool must never be wrong
    in.
    """
    if path.endswith(".mojo"):
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            tree = ast.parse(f.read(), filename=path)
    except Exception:                                   # noqa: BLE001
        return None
    top = module.split(".")[0]
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                used.add(base.id)
    if top in used:
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module \
                and node.module.split(".")[0] == top:
            for alias in node.names:
                if (alias.asname or alias.name) in used:
                    return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == top \
                        and (alias.asname or top) in used:
                    return True
    return False


def _host_refusal_clause(name: str, source_path: str):
    """The clause `formal/imports.py` puts in the refusal for `name`, or None.

    **READ, NOT COPIED, and that is the whole point of the function.**
    `print_host_table` used to quote a sentence here — "not a stdlib or sibling
    module, and no such file exists" — as what a module in neither tier is
    refused with, and that sentence stopped being what the build says when
    `formal/imports.py::unresolvable_import_error` grew its third wording
    (`bugs/FORMAL_stdlib_module_names_are_not_classified.md` §0): a name CPython
    ships and no tier names is now told it is "a CPython standard-library module,
    which has no Mojo source in this tree and no tier … saying whether
    implementing it would need an object this target does not have". So the
    ranking instrument was quoting a sentence the compiler cannot emit, on the
    three modules the ranking itself found — which is a report disagreeing with
    the message it reports on, the same defect `tools/formal_sweep.py`'s
    `_is_cpython_stdlib` had before it became a delegation.

    `source_path` is one of the files the row actually blocked, so the clause
    printed is the one THAT file was given rather than a reconstruction: the
    table's subject is what the sweep recorded, and a synthetic path would make
    the note about a file nobody has heard of.

    The `host_module_advice` sentence the same function appends is subtracted by
    LENGTH rather than split on a delimiter, so advice of its own that contains
    a `; ` cannot eat the end of the clause. None when `formal.imports` cannot be
    imported here, and the caller then says the clause could not be read — the
    same discipline every other unmeasurable column in this table follows.
    """
    try:
        from formal.imports import unresolvable_import_error, host_module_advice
        text = unresolvable_import_error(source_path, name)
    except Exception:                                   # noqa: BLE001
        return None
    marker = f"imports {name!r}, which is "
    start = text.find(marker)
    if start < 0:
        return None
    clause = text[start + len(marker):]
    try:
        advice = host_module_advice(name)
    except Exception:                                   # noqa: BLE001
        advice = ""
    tail = f"; {advice}" if advice else ""
    if tail and clause.endswith(tail):
        clause = clause[:-len(tail)]
    return clause or None


def _host_tier(name: str):
    """`formal/imports.py`'s own answer, read through its published accessor."""
    try:
        from formal.imports import host_module_tier
        return host_module_tier(name)
    except Exception:                                   # noqa: BLE001
        return ""


def _host_verdict_label(name: str) -> str:
    """What this table's `tier` column prints for `name`, from ONE accessor.

    A module with a source is WRITTEN, which is a third state and not a missing
    one: it is in neither tier because `HOST_MODELLED`'s rule is "a name LEAVES
    here by being WRITTEN" and `HOST_ADMITTED`'s is "a name is here iff it has a
    source", and its import resolves before either set is consulted. So the
    column prints `written` for those, and `host_module_tier`'s `''` — which is
    ambiguous between "written" and "nobody classified it" — is not read here at
    all.

    **It used to be read here, and inferred from `formal/hostmods/`.** That is a
    THIRD definition of the same fact: a name this repository answers with a
    sibling `.py`, or with a package `__init__.mojo` outside `formal/hostmods/`,
    came out `UNTIERED` — which is a defect claim about a module that is
    answered. `formal.imports.host_module_verdict` is the one classification,
    every answer named, and this is a label over it rather than a second answer.
    """
    try:
        from formal.imports import host_module_verdict
        answer, _detail = host_module_verdict(name)
    except Exception:                                   # noqa: BLE001
        return "UNTIERED"
    # `unclassified` is the answer that means "CPython ships it and no tier says
    # which kind of name it is", and it is what this table has always printed as
    # UNTIERED with the refusal's own words spelled out underneath the row.
    return "UNTIERED" if answer == "unclassified" else answer


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
        # The fallback for a module whose NAMES could not be read, and it is a
        # different question rather than a worse answer to the same one: not
        # "which of its names does this file bind" but "does this file spell the
        # module AT ALL". Zero is a sound answer in that question — no file
        # spells `zlib` in code, so no file can be using whatever `zlib` exports
        # — and it is the answer that says a row of N files is N files of
        # CLOSURE. One or more is a LOWER BOUND and is printed as one, and a
        # file that does not tokenize leaves the whole column unmeasured rather
        # than counting as a non-user.
        mentions = None
        if declared is None:
            seen = [_host_mentions_module(f, mod) for f in per_file]
            if all(s is not None for s in seen):
                mentions = sum(1 for s in seen if s)
        out.append({
            "module": mod,
            "files": len(files),
            "uses": uses,
            "mentions": mentions,
            # Sorted by (count, name) and not left to `most_common`, which
            # breaks a TIE in insertion order — and the insertion order comes
            # out of a `set` of names read from a `dict`, so two runs of the
            # same log printed `module_from_spec x4, spec_from_file_location x4`
            # and then the other way round (measured, same tree, same log). A
            # column that reorders itself between runs is a table nobody can
            # read as a diff, which is the same reason the `example` row below
            # is sorted rather than taken first.
            "names": sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))[:8],
            "declared_known": declared is not None,
            "declared": declared or (),
            "tier": _host_tier(mod),
            "verdict": _host_verdict_label(mod),
            "model": _host_model_source(mod),
            # IN NO TIER is only a DEFECT when the name is UNCLASSIFIED, which
            # is what `host_module_verdict` says rather than what the absence of
            # a tier entry says: a module that has been WRITTEN is in no tier by
            # design (`HOST_MODELLED`'s rule is "a name LEAVES here by being
            # WRITTEN", `HOST_ADMITTED`'s is "a name is here iff it has a
            # source"), and its import resolves before either set is consulted.
            # `os`, `sys` and `re` are in no tier for that reason and are not
            # mis-diagnosed; `datetime` and `builtins` are in no tier because
            # nobody classified them, and every file that wants one is told it is
            # a CPython standard-library module this tree has no source or tier
            # for — a name with no owner and no next step, which is the state
            # worth printing. The WORDS of that are asked for rather than written
            # here, for the reason `_host_refusal_clause` states.
            "untiered": _host_verdict_label(mod) == "UNTIERED",
            # ONE of the files the row blocked, and the subject of the note
            # printed under it. Sorted, so the note names the same file on every
            # run of the same log — a row whose note quoted a different file each
            # time would be unreadable as a diff.
            "example": sorted(files)[0] if files else "",
        })
    out.sort(key=lambda r: (-r["files"], r["module"]))
    return out, lines, len(files_all)


def print_host_table(table, minimum, lines=0, files_all=0):
    print(f"{'files':>5} {'uses':>5}  {'tier':<11} {'model':<26} host module")
    for r in table:
        if r["files"] < minimum:
            continue
        # A module with a source is WRITTEN, which is a third state and not a
        # missing one, and the label comes from `formal.imports.host_module_verdict`
        # so this table and the build cannot answer differently about one name.
        tier = r["verdict"]
        model = r["model"] or "—"
        uses = r["uses"] if r["declared_known"] else (
            "?" if r["mentions"] is None
            else ("0" if r["mentions"] == 0 else f">={r['mentions']}"))
        print(f"{r['files']:>5} {str(uses):>5}  {tier:<11} {model:<26} "
              f"{r['module']}")
        if r["mentions"] == 0:
            print(f"        uses:        0 — no blocked file READS "
                  f"{r['module']}: not one imports it and binds something it "
                  f"then uses in code (a comment or a string is not a use), so "
                  f"the row is import CLOSURE whatever {r['module']} exports — "
                  f"the imports that stopped these {r['files']} files read "
                  f"nothing from it")
        elif r["mentions"]:
            print(f"        uses:        >={r['mentions']} — a LOWER BOUND: "
                  f"{r['module']} has no source in this interpreter's stdlib, "
                  f"so which of its names these files bind cannot be counted, "
                  f"and this is how many of them spell it at all")
        elif not r["declared_known"]:
            print(f"        uses:        NOT MEASURED: {r['module']} has no "
                  f"source in this interpreter's stdlib (it is built in or "
                  f"frozen), so nothing here can be counted, and at least one "
                  f"blocked file is not a `.py` this could read the imports of, "
                  f"so even the fallback (does any file use the module at all) "
                  f"is open")
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
            clause = _host_refusal_clause(r["module"], r["example"])
            if clause:
                print(f"        UNTIERED:    {r['module']} is in NEITHER "
                      f"formal/imports.py tier, so {r['example']} is refused "
                      f"as \"{clause}\" — a name with no owner and no next step")
            else:
                print(f"        UNTIERED:    {r['module']} is in NEITHER "
                      f"formal/imports.py tier and has no model, so a file that "
                      f"imports it gets a refusal with no owner and no next step. "
                      f"NOT MEASURED: formal/imports.py could not be imported "
                      f"here, so what that refusal SAYS is not quoted")
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
    print("`UNTIERED` quotes formal/imports.py::unresolvable_import_error rather "
          "than the build's wording\nwritten out here, so the clause under a "
          "row is the one that file was given.")


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

    table, total, unclassified = rank(args.log)
    shown = [r for r in table if r["files"] >= args.minimum]
    if args.json:
        json.dump(shown, sys.stdout, indent=1)
        print()
        return 0
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

    # THE UNCLASSIFIED BUCKET, LOUDLY, and it is `formal_sweep.py`'s alarm
    # rather than a second one: its `unclassified_report` owns the shape
    # grouping, the threshold and the wording, and this table calls it with ITS
    # OWN classifier's unclassified rows and with the sweep's family table as the
    # other opinion — so a shape this table cannot name but the sweep's can is
    # reported here as a one-row fix in `CAUSES`, and a shape NEITHER can name
    # is reported as what it is, which is the 2026-10-04 b12 failure: 236 of this
    # table's files, the corpus's largest row, found by reading a work map
    # afterwards instead of by running anything.
    #
    # The exit status is unchanged, and the module docstring's rule is why: this
    # tool reports on another tool's output and has no opinion about it. The
    # sweep that produced the log is the thing that exits 4, over the same rows
    # measured by the same function.
    print()
    FS.unclassified_report(unclassified, _swept(args.log),
                           other_classify=FS._refusal_family,
                           other_name="formal_sweep.py's _REFUSAL_FAMILIES")
    return 0


def _swept(log_path):
    """The file total from a sweep log's own summary line, or 0 if it has none.

    Read for the SHARE half of the honesty bar, and a missing line is 0 rather
    than a guess: with no denominator the bar is the file count alone, which is
    the stricter of the two, so a log without a summary line under-reports the
    finding instead of inventing one.
    """
    with open(log_path, errors="replace") as f:
        for raw in f:
            m = FS.SUMMARY_RE.match(raw)
            if m:
                return int(m.group("files"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
