#!/usr/bin/env python3
"""The refusal taxonomy must stay a taxonomy.

Measured 2026-09-28, arm64: 130 in-file codegen findings resolved to 104
distinct message TEXTS, and 123 of the 130 landed in one bucket called "other
refusal". So the sweep could say that 25.9% of the denominator was blocked and
name none of it — which is the specific thing a family table exists to prevent.

It is now 20 families and zero "other". Two things about that are worth
protecting, and they are not the same thing:

1. **Precedence.** `_refusal_family` takes the FIRST marker that matches, so
   position in the tuple is load-bearing. A perfectly good marker placed after
   a broader one is dead code, and it fails silently: the broader family claims
   the message and the count is simply wrong. The real case here was "which is
   a name with no definition in hand", which appears *inside* a message that
   begins "a X receiver is passed to ..." — 11 findings were being counted as
   a receiver problem, which is a number in the wrong column. That is worse than
   having no taxonomy, so it is worth a test rather than a code comment.

2. **Rot.** Every marker is a substring of a message the backend actually
   produced. A marker that stops matching does not fail — the family goes
   quietly unused and its findings fall back into whatever matches next, or
   into "other". The samples below are real messages, abbreviated at clause
   boundaries, and each asserts the family it must land in.

Run:  python3 test_refusal_taxonomy.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_sweep as S  # noqa: E402
import formal_sweep_causes as C  # noqa: E402

# (family, a real message, truncated only at a clause boundary)
SAMPLES = [
    # The frame-address families. All one design defect, five costumes; the
    # distinction is which fix applies.
    ("frame address escapes: returned by its creator",
     "a String receiver is returned from the function that created it on this "
     "path: the receiver of a multi-field struct is the ADDRESS of a frame"),
    ("frame address escapes: aliased out of a method",
     "a Progress receiver is returned from a method of Progress, which did not "
     "create the frame — it received the address as its receiver"),
    ("frame address passed where a value is wanted",
     "a BinaryHeap frame address is passed to len(), which is lowered as an "
     "operation on a VALUE: it wants the object itself"),
    ("receiver passed as an argument",
     "a _WriteBufferStack receiver is passed to ?.write_to in argument "
     "position 0, and a method call on a value receiver is dispatched by NAME"),
    ("field slot holds a frame address",
     "self.asm.org() hands the word in the slot self.asm to Assembler.org(), "
     "whose receiver is the ADDRESS of a frame of 8-byte slots"),
    ("name has two disagreeing shapes",
     "x.y cannot be placed: this name holds a frame address in more than one "
     "shape, and the shapes do not agree"),
    # The two shapes the message above was ALSO matching, before
    # `formal/model.py`'s `member_read_without_a_field` told the two apart: it
    # printed "more than one shape … the shapes do not agree" for a SINGLE
    # candidate with nothing to disagree about, which put 4 files of row 13 in a
    # family about a disagreement that did not exist. They need families of
    # their own or they land in "other refusal" — which is the exact failure this
    # file exists to catch, introduced by fixing a diagnostic.
    ("member read of a method used as a value",
     "self._untyped_callee names '_untyped_callee', which is a METHOD of "
     "ARM64Codegen rather than one of its fields"),
    ("member read of a name the struct does not have",
     "gen.type_checker is a field of gen, and GimpleGen has no field "
     "'type_checker'"),
    # The precedence case. This message contains "receiver is passed to" AND
    # "which is a name with no definition in hand", and must take the second.
    ("callee has no definition on this path",
     "a String receiver is passed to _b64encode(), which is a name with no "
     "definition in hand: this module's own functions are the only ones in "
     "this image"),
    # The one frame family that CRASHES rather than computing a wrong number.
    ("self has two kinds of value across call sites",
     "Random_step() takes a Random receiver at argument 0 — 'self' — at "
     "Random_step(self) here, and something that is not a frame address at "
     "Random_step(self._rng)"),
    # The rest.
    # MLIR. Three kinds of thing reach this bucket: a dialect attribute
    # template, a dialect operation, and a construct that names a TYPE — which
    # the old fixed word called an attribute, false of every `__mlir_type`
    # binding in the stdlib including `std/sys/info.mojo`'s `_TargetType`, the
    # module that heads this family.
    ("MLIR construct",
     "materialize: __mlir_op is an MLIR dialect construct. This path has no "
     "MLIR: it lowers a Mojo program to a Mach-O image"),
    ("MLIR construct",
     "the module-level comptime binding '_PLUGIN_COUNT' is initialized from an "
     "MLIR attribute template: __mlir_attr[`#kgen.param_list.size<:`,"),
    ("MLIR construct",
     "the module-level comptime binding 'AnyCoroutine' is initialized from an "
     "MLIR type template: __mlir_type.`!co.routine` names an MLIR TYPE, not a "
     "value"),
    # The current target as a VALUE. A different limit from the dialect
    # attributes above, with a different repair, and the message says so: the
    # same target's FIELDS do answer, so "there is no MLIR on this path" would
    # be a claim about the file that is false.
    ("MLIR construct",
     "return: __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target` "
     "asks for the current TARGET itself, which is not a value on this path"),
    # A QUESTION this build cannot answer, its own family because the fix is
    # specific: the backend states the architecture it emits and the container
    # it wraps it in, and a per-CPU question needs neither. ONE marker for the
    # whole class, so the three specific wordings behind it are counted as the
    # limit they are instead of falling through to whatever matches next.
    ("target query not answerable",
     "target_has_feature('neon') is a per-CPU question: this build cannot "
     "answer this target query: a CPU feature is a property of a CPU"),
    ("target query not answerable",
     "this build cannot answer this target query: the current target "
     "arm64/darwin has no 'triple' for this build to state"),
    ("target query not answerable",
     "this build cannot answer this target query: an argument of the 'eq' "
     "query is neither a literal nor another query this build can read"),
    ("nested frame field read",
     "self._handle._get_ctx reads '_get_ctx' out of a nested RaisingCoroutine "
     "frame, and that struct's 2 field(s): origins, _handle has no such"),
    ("comptime does not fold",
     "comptime num_coefficients = ... does not fold to a compile-time constant "
     "on this path, so there is no value to materialize"),
    ("comptime does not fold",
     "_serialize_elements_compact: '_kCompactElemPerSide' is a `comptime` "
     "binding declared at module level, and it does not fold to a compile-time "
     "constant on this path"),
    ("unimplemented intrinsic",
     "a `...` stands where this path needs instructions to emit, and there are "
     "none: a formal image is a compiled program"),
    ("variadic call has no ABI",
     "tile: the body reads 'tile_size_list', its *-parameter, and this path "
     "has no variadic ABI"),
    ("unsupported construct (parse error)",
     "parse error: /x/std/algorithm/reduction.mojo:251:7: `comptime { … }` and "
     "`comptime <expr>` are not supported by this compiler"),
    ("construction with arguments needs __init__",
     "constructing FuncAttribute with 2 argument(s) is a call to a "
     "user-defined `__init__` and none of them takes that count"),
    ("receiver stored in a container",
     "a Optional receiver is stored in a container, which has no layout for a "
     "frame address on this path"),
    ("module-global name has no storage",
     "type_to_c: 'MLIR_TYPES' is bound at module level, and this path has no "
     "module-global storage for it: a formal value lives in a function's own"),
    ("method call on a value",
     "writer.write_string() is a method on a Writer — a multi-field struct, so "
     "on this path the receiver is the ADDRESS of a frame of 8-byte slots"),
]

# ── the SECOND table: `tools/formal_sweep_causes.py` ────────────────────────
# Same disease, one level up. `formal_sweep._REFUSAL_FAMILIES` above groups a
# printed line for the sweep's own breakdown; `formal_sweep_causes.CAUSES` is
# the table a PLANNER reads, keyed on what a fix would have to change rather
# than on the shape of the message. It has its own markers, its own ordering,
# and therefore its own rot — and rot there is worse, because the number it
# produces is the one someone acts on.
#
# Both rot modes below were real on 2026-09-30, found by re-running the sweep
# and diffing the table against the map written from the previous one:
#
#   * a marker whose message was REWORDED stops matching, and its findings
#     fall into `other refusal` — the bucket that means "this tool has not
#     classified this". `formal-module-attr` changed "… SO it is a
#     module-level name of another module" to "… AND it is …", and four
#     findings left that row with nothing to report it.
#   * a marker that is the FAMILY NAME rather than something a message
#     contains (`unimplemented intrinsic`, which no message in the tree
#     contains) can never match, and reads as a cause that blocks nothing.
#
# So: one real message per cause, abbreviated at clause boundaries exactly as
# above, and every cause must be reached by at least one of them. Cut from the
# 2026-09-30 r2 arm64 sweep (637 files, log in the worktree that produced
# `bugs/FORMAL_sweep_work_map_2026-09-30_r2.md`).
CAUSE_SAMPLES = [
    ("MLIR dialect construct (__mlir_attr / __mlir_type / __mlir_op)",
     "the module-level comptime binding '_PLUGIN_COUNT' is initialized from an "
     "MLIR attribute template: __mlir_attr[`#kgen.param_list.size<`"),
    ("inlined_assembly (a gimple-C runtime construct)",
     "inlined_assembly: 'NoneType' has no home: this module declares no "
     "module-level name by that spelling"),
    ("module exports no public functions",
     "formal dylib has no public functions: binary_heap.mojo exports nothing "
     "under doc/ABI.md's rules: it declares only the generic struct "
     "template(s) BinaryHeap"),
    ("a linked module exports no such name",
     "sys.exit(): `sys` is a linked module but it exports no `exit`, so the "
     "call has nothing to bind"),
    ("a TYPE name placed as a value (`L[T]()` or `DType.bool`)",
     "FuncAttribute_MAX_DYNAMIC_SHARED_SIZE_BYTES: 'DType' has no home: this "
     "module declares no module-level name by that spelling"),
    ("a module-global name has no storage",
     "encode_sxtb_wd_wn: '_SXT_BASES' is bound at module level, and this path "
     "has no module-global storage for it"),
    ("a module-level name of ANOTHER module is not exported as a word",
     "main: 'sys' is imported from `sys`, and it is a module-level name of "
     "another module. This path compiles an import into a dylib"),
    ("method parameter's field, with no call site to establish it",
     "Slice___eq__: 'other.start' is a field access through 'other', and this "
     "path has no way to say what 'other' holds"),
    ("frame address escapes: returned by its creator",
     "a String receiver is returned from the function that created it on this "
     "path: the receiver of a multi-field struct is the ADDRESS of a frame"),
    ("frame address escapes: aliased out of a method",
     "a Progress receiver is returned from a method of Progress, which did not "
     "create the frame — it received the address as its receiver"),
    ("frame address passed where a value is wanted",
     "a Tuple frame address is passed to origin_of(), which is lowered as an "
     "operation on a VALUE"),
    ("receiver stored in a container",
     "a Optional receiver is stored in a container, which has no layout for a "
     "frame address on this path"),
    ("a field of a field: a frame slot holds one word, not a struct",
     "self._dict._table._ctrl reads a field of a field through the receiver"),
    ("a field of a nested frame that the struct does not declare",
     "self._slice._slice._data reads '_data' out of a nested StringSlice frame"),
    ("a slot's declared type is not declared by its struct",
     "self.asm.org() hands the word in the slot self.asm to Assembler.org(), "
     "whose receiver is the ADDRESS of a frame of 8-byte slots — so the slot "
     "would have to hold a frame address. The declared type of 'asm' is the "
     "only thing here that could say so, and it does not"),
    ("a name holds a frame address in more than one shape",
     "gen.type_checker cannot be placed: this name holds a frame address in "
     "more than one shape"),
    ("one parameter, two kinds of value across call sites",
     "Random_step() takes a Random receiver at argument 0 — 'self' — at "
     "Random_step(self) here, and something that is not a frame address at "
     "Random_step(self._rng). One parameter, two kinds of value"),
    ("a slot's declared type is not a value this path can supply",
     "len(self._data) — this slot's DECLARED type is 'List[Self.T]', so the "
     "value the slot holds is not one"),
    ("callee has no definition on this path",
     "a String receiver is passed to _b64encode(), which is a name with no "
     "definition in hand"),
    ("receiver passed at argument position 0",
     "a Coord receiver is passed to the call in argument position 0, and a "
     "method call on a value receiver is dispatched by NAME"),
    ("struct construction: arity does not match the fields",
     "constructing LaunchError with 1 argument(s) does not match its fields"),
    ("a `...` body: no instructions to emit",
     "a `...` stands where this path needs instructions to emit, and there are "
     "none"),
    ("`==` between two values whose kind no call site established",
     "`_name_len(...) == nlen` compares two values this path can only call "
     "numbers, and at least one of them arrived from a call that does not say "
     "what it returns"),
    ("print() cannot classify the argument's type",
     "print() cannot tell whether SubscriptExpr is a string or a number on "
     "this path"),
    ("len() of a value that has no length",
     "len(s) is len() of a value classified as 'int', and an integer has no "
     "length"),
    ("a method on a multi-field struct where a descriptor is meant",
     "writer.write_string() is a method on a Writer — a multi-field struct, so "
     "on this path the receiver is the ADDRESS of a frame"),
    ("too many parameters for the arm64 register ABI",
     "_build_segment_64: 9 parameters exceeds the 8 the formal arm64 ABI "
     "passes in registers"),
    ("comptime does not fold to a constant",
     "comptime num_coefficients = ... does not fold to a compile-time "
     "constant on this path"),
    ("variadic call has no ABI",
     "tile: the body reads 'tile_size_list', its *-parameter, and this path "
     "has no variadic ABI"),
    ("method call on a value receiver is not one of the lowered methods",
     "value.write_repr_to() is a method call on a value, and this backend "
     "lowers only append, close, write"),
    ("a class-level default is the NAME `None`",
     "SideResult.harness_error: the default for field 'harness_error' is "
     "`None`, and on this path `None` is a NAME rather than a literal"),
    ("multi-index subscript",
     "size_of[type, target] is a subscript whose index is a tuple. A value "
     "here is one 64-bit word and a list is a flat blob of words, so a tuple "
     "index has no representation on this path"),
    # NOTE the order boundary this one sits on: the message opens with the
    # receiver sentence the frame-address cause keys on and only reaches its
    # own marker in the second clause, so a sample abbreviated before that
    # clause would be classified as a receiver problem — which is what the
    # FIRST cause in the file does to it, and the reason this sample has to
    # keep its tail.
    ("value with no representation on this path",
     "a String frame address is passed to Error(), and Error is a real type "
     "this path has no representation for at all: one formal value is one "
     "64-bit word, and Error is not one word"),
]

# The causes no arm64 message above exercises. Each one is named here with WHY,
# because a silent exemption is the thing this file exists to prevent — an
# unnamed gap in the table reads as a cause nobody has hit yet, which is a
# claim about the world rather than about this file.
NO_ARM64_SAMPLE = {
    "write(2) receiver is not a file descriptor":
        "the message is `X() lowers to the C library's write(2), so its "
        "receiver has to be …` (formal/model.py, with {method} interpolated); "
        "no file in the 2026-09-30 sweeps reached it",
    "receiver passed to a call, position not stated":
        "the generic `… is passed to …` catch-all of the receiver family; every "
        "message that matches it in a real sweep is claimed by one of the "
        "three causes above it, which is what the precedence check below "
        "asserts",
}


def check_cause_table(failures):
    """Every cause is reachable from a real message, and nothing shadows it."""
    labels = [label for label, _ in C.CAUSES]
    if len(labels) != len(set(labels)):
        failures.append(
            "two causes share a label, so the table cannot say which one a "
            "reader is looking at: "
            + ", ".join(sorted(l for l in set(labels) if labels.count(l) > 1)))

    for label, msg in CAUSE_SAMPLES:
        got = C.classify_message(msg)
        if got != label:
            failures.append(
                f"cause: expected {label!r}, got {got!r}\n"
                f"    message: {msg[:100]}")

    reached = {C.classify_message(msg) for _l, msg in CAUSE_SAMPLES}
    for label in labels:
        if label not in reached and label not in NO_ARM64_SAMPLE:
            failures.append(
                f"cause {label!r} matches no real message and is not in "
                f"NO_ARM64_SAMPLE. Either its marker is stale — a message was "
                f"reworded and this cause now collects nothing while reading "
                f"as one that blocks nothing — or the cause needs a sample "
                f"here")
    for label in NO_ARM64_SAMPLE:
        if label not in labels:
            failures.append(
                f"NO_ARM64_SAMPLE names {label!r}, which is no longer a cause; "
                f"the exemption outlived the thing it excuses")

    # The reword, as a case rather than as a comment: both wordings of the
    # module-level-name refusal are classified to the SAME cause, so the table
    # reads an old sweep log and a new one identically.
    label = "a module-level name of ANOTHER module is not exported as a word"
    for connector in ("so it is", "and it is"):
        msg = (f"main: 'sys' is imported from `sys`, {connector} a module-level "
               "name of another module. This path compiles an import into a "
               "dylib, and a dylib publishes FUNCTIONS and folded CONSTANTS")
        if C.classify_message(msg) != label:
            failures.append(
                f"the {connector!r} wording of the module-level-name refusal "
                f"fell out of its cause: got "
                f"{C.classify_message(msg)!r}. Keep BOTH wordings — a sweep log "
                f"is an artifact and the table has to read the old ones too")

    # Precedence, stated independently of the samples so a future edit cannot
    # satisfy them by deleting a marker. The multi-index message ends with the
    # BROAD cause's sentence, so the specific cause has to be asked first.
    multi = ("size_of[type, target] is a subscript whose index is a tuple. A "
             "value here is one 64-bit word, so a tuple index has no "
             "representation on this path")
    if C.classify_message(multi) != "multi-index subscript":
        failures.append(
            "the multi-index cause is shadowed by the broad `has no "
            "representation on this path` one, whose sentence the multi-index "
            "message ends with; it can never match where it stands")
    pre = ("a X receiver is passed to foo(), which is a name with no "
           "definition in hand")
    if C.classify_message(pre) != "callee has no definition on this path":
        failures.append(
            "the 'callee has no definition' cause is being shadowed by a "
            "broader receiver cause; its findings are counted as a receiver "
            f"problem again (got {C.classify_message(pre)!r})")


def main() -> int:
    failures = []

    for family, msg in SAMPLES:
        got = S._refusal_family(msg)
        if got != family:
            failures.append(
                f"expected {family!r}, got {got!r}\n"
                f"    message: {msg[:100]}")

    check_cause_table(failures)

    # The precedence rule, stated independently of the samples above so a
    # future edit cannot satisfy SAMPLES by deleting a marker outright.
    pre = ("a X receiver is passed to foo(), which is a name with no "
           "definition in hand")
    if S._refusal_family(pre) != "callee has no definition on this path":
        failures.append(
            "the 'callee has no definition' marker is being shadowed by a "
            "broader receiver marker; its findings are counted as a receiver "
            f"problem again (got {S._refusal_family(pre)!r})")

    # Every family name is distinct and readable, and none is the catch-all.
    names = [f for _m, f in S._REFUSAL_FAMILIES]
    if S._REFUSAL_OTHER in names:
        failures.append(
            f"{S._REFUSAL_OTHER!r} is in _REFUSAL_FAMILIES, so the catch-all "
            "can match and findings stop being visible as unclassified")

    # A marker that is a GENERIC phrase would swallow the families above it and
    # quietly defeat the whole table. The obvious version is a bare English
    # word. A code token is NOT the same thing: `__mlir_` is one identifier
    # prefix and is about as specific as a marker can be, so markers that look
    # like code are exempt.
    for marker, family in S._REFUSAL_FAMILIES:
        looks_like_code = ("_" in marker or "(" in marker or "." in marker)
        if len(marker.split()) < 3 and " " not in marker and not looks_like_code:
            failures.append(
                f"marker {marker!r} (family {family!r}) is a bare word; a "
                "generic marker placed early would claim messages the more "
                "specific markers below it were written for")

    for f in failures:
        print("  FAIL  " + f)
    checks = (len(SAMPLES) + 3 + len(CAUSE_SAMPLES) + len(C.CAUSES) + 4)
    print(f"\nrefusal taxonomy: {'PASS' if not failures else 'FAIL'} "
          f"({checks - len(failures)}/{checks} checks, "
          f"{len(set(names))} families, {len(C.CAUSES)} causes)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
