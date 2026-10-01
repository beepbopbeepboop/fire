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

3. **A count that reads like a gap and is not one.** The cause table in
   `tools/formal_sweep_causes.py` ranks by what a fix would have to CHANGE, and
   prints `FILES BLOCKED` with an explicit warning that it is an upper bound.
   For a cause whose refusal is about a MODULE's boundary rather than a
   construct in the swept file, the bound is loose enough to invert the
   decision: `module exports no public functions` was 38 files, 35 of them
   behind `std/collections/binary_heap.mojo`, and 34 of those 35 contain no
   occurrence of `BinaryHeap` at all — the formal backend builds a dylib for
   every module in a file's EAGER import closure, so a module with no boundary
   symbol refuses importers that bind nothing in it. That is why the table also
   prints `uses:` (how many of a module's blocked files name anything it
   declares), and the section below pins it: a `uses` column that is always 0,
   that matches substrings, or that reports "I could not find the module" as a
   measured 0, is worse than no column. Measured ceilings, both 0 files:
   `bugs/FORMAL_dylib_export_gate_ceiling.md`.

Run:  python3 test_refusal_taxonomy.py
"""
import os
import sys
import tempfile

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
    # The TYPE spelling, which is the one `formal/model.py` computes from the
    # node (`kind = "type" if is_mlir_type_template(node) else "attribute"`).
    # It is a SEPARATE sample rather than a variant of the one above because
    # `classify_message` sees only the message: one sample in a cause is one
    # proof its marker matches, and a marker added for the type wording that no
    # sample exercised is exactly the dead-marker failure this file exists for.
    ("MLIR dialect construct (__mlir_attr / __mlir_type / __mlir_op)",
     "the module-level comptime binding '_dtype_to_llvm_type_f8' is initialized "
     "from an MLIR type template: __mlir_type.`i8` names an MLIR TYPE, not a "
     "value"),
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
    # The three causes below, plus the MLIR row's fourth wording, were all
    # added on 2026-10-01 from the b3 sweep, and every one of them is a marker
    # that was MISSING rather than one that had gone stale: each shape had files
    # in it and the table could not see them, so `other refusal` read 183 files
    # where the classified rows below read 50. Samples are cut from that run's
    # own arm64 log, abbreviated at clause boundaries as above.
    ("receiver stored in a field of a struct that outlives it",
     "a Optional receiver is stored in the field 'self.start', so it outlives "
     "the frame it names by however long that object lives: the slot belongs to "
     "the function that created THAT frame"),
    ("a parameter's declared type contradicts every call site",
     "b64encode() declares 'result' as String, so it is compiled with 'result' "
     "as the ADDRESS of a frame of 8-byte slots — and every call site in this "
     "image hands it something else: b64encode(input_bytes, result) passes a "
     "name, 'result'"),
    ("a bracketed specialization of a callee this unit does not compile",
     "debug_assert[…](…) calls a name this unit does not compile, so the "
     "brackets cannot be bound. A comptime specialization's brackets are the "
     "generic's comptime parameters"),
    ("a field of a field: a frame slot holds one word, not a struct",
     "self._dict._table._ctrl reads a field of a field through the receiver"),
    ("a field of a nested frame that the struct does not declare",
     "self._slice._slice._data reads '_data' out of a nested StringSlice frame"),
    # The OLD wording of the slot sentence, kept as a sample of the row that
    # now owns it. `formal/build.py:2731` reworded its tail ("The declared type
    # of 'asm' is the only thing here that could say so, and it does not" →
    # "Only a type for 'asm' could say so … and there is no single one"), the
    # old row's two markers were both IN that tail, and the row went to 0 files
    # on both arches without anything failing. This sample is what makes that
    # visible: it is a real message (quoted in full, with the file it came
    # from, in `bugs/FORMAL_frame_receiver_handoff.md` §D2) and it classifies
    # to the row that owns the construct.
    ("the slot would have to hold a frame address, and no type says so",
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
    # TWO samples, one cause: this row is the register-argument count and both
    # architectures word it from the same f-string with their own constant
    # interpolated (`_ABI_ARG_REGS` = 8, `len(ARG_REGS)` = 6), so a table that
    # only knew the arm64 number read 57 x86-64 files as unclassified. Both
    # wordings are real messages from the 2026-10-01 r2 logs, one per arch.
    ("too many parameters for the register ABI (8 on arm64, 6 on x86-64)",
     "_build_segment_64: 9 parameters exceeds the 8 the formal arm64 ABI "
     "passes in registers"),
    ("too many parameters for the register ABI (8 on arm64, 6 on x86-64)",
     "b2_g: 7 parameters exceeds the 6 the formal x86-64 ABI passes in "
     "registers"),
    # The two x86-64-only refusals. They are the two files whose message DIFFERS
    # between architectures on an otherwise class-identical sweep
    # (`bugs/FORMAL_known_limits.md` §6.5), and they are here because the doc
    # had measured the drift the table could not show.
    ("an operator the x86-64 codegen does not lower",
     "unsupported unary operator '^' on the formal x86-64 path"),
    ("a call target the x86-64 codegen does not lower",
     "unsupported call target on the formal x86-64 path (got SubscriptExpr)"),
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
    # ── the rows added by the 2026-10-01 r2 split of the `other refusal`
    #    bucket (50 files on arm64, 104 on x86-64, down to 4 and 4). Cut from
    #    the r2 logs of THIS tree, arm64 unless the sample says otherwise, and
    #    each one is the terminal message a planner would have to go and read
    #    by hand out of a bucket that meant "this tool has not classified
    #    this". ──
    ("Optional unwrap: `None` and a value are one word, with no tag",
     "self.step.or_else() is an Optional unwrap: it answers by knowing which "
     "of two words was the empty one, and on this path there is no way to "
     "know"),
    ("the slot would have to hold a frame address, and no type says so",
     "self._slice._slice._data.unsafe_offset() hands the word in the slot "
     "self._data to Pointer.unsafe_offset(), whose receiver is the ADDRESS of "
     "a frame of 8-byte slots — so the slot would have to hold a frame "
     "address"),
    # Both wordings of the rebind row, because the two sites are two walkers
    # and a refactor could break either one alone.
    ("a slot holding a frame address is rebound by a later assignment",
     "self._slots is a Pointer, a struct of this module whose receiver is a "
     "frame of 8-byte slots, so the slot does hold a frame address — but a "
     "method of SwissTable ASSIGNS that field"),
    ("a slot holding a frame address is rebound by a later assignment",
     "atom is assigned _Parser_parse_atom(self) in _Parser_parse_repeat(), and "
     "atom also holds the address of a Repeat frame — Repeat() binds it to "
     "one, and this path has no way to say that a later binding changes what "
     "the name is"),
    ("a field the struct does not declare — CPython raises AttributeError too",
     "res._InjectedValues is a field of res, and _ZipIterator has no field "
     "'_InjectedValues': its 2 field(s): origin, _values"),
    ("a field the struct does not declare — CPython raises AttributeError too",
     "shape.is_flat is a field of shape, and Coord has no field 'is_flat': "
     "its 3 field(s): _storage, rank, product"),
    ("a NUMBER compared with a string (`strcmp` would dereference it)",
     "`_v == '1'` compares a NUMBER with a string, and the string comparison "
     "this would lower to is `strcmp`, which DEREFERENCES both operands"),
    ("a module-global container has storage but no initializer",
     "arch_spec: 'ARCHES' has storage here — it is one of the module-global "
     "slots in this image's `__DATA`, because a function writes it through "
     "`global ARCHES` — but that storage has no initializer"),
    ("`field(default_factory=F)`: nowhere to keep a per-instance value",
     "CallExpr.args: `field(default_factory=F)` calls F once per instance, "
     "and this path has nowhere to keep the result"),
    ("a constructor body that reads `self` is not inlined",
     "constructing ModuleSpecGenerator with arguments is a call to a "
     "user-defined `__init__` whose body this path does not inline: a read of "
     "'self' in the right-hand side"),
    ("a module whose API is its top-level statements, imported by another",
     "ab_filelist.py: line 12: this module's API is its top-level statements "
     "(AssignStmt, IfStmt), and a library has no entry point to run them"),
    ("a local read before its first assignment",
     "load: 'f' is read at line 22 before anything in this function stores "
     "it, and CPython raises UnboundLocalError for that program"),
    ("a class-level default that is not a value this build can materialize",
     "Type.origin: the default for field 'origin' is not a value this build "
     "can materialize, and a class-level default on this path has to be one"),
    ("a String method that returns a SHORTER string writes the receiver's "
     "bytes",
     "member.strip() is a real method of String, but it returns a SHORTER "
     "string, which on a bare char * means writing a terminator over the "
     "first trailing whitespace byte"),
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
    # DEAD, and measured dead: 0 files on the 2026-10-01 r2 sweep on BOTH
    # architectures. Its site reworded the tail of its message, both its
    # markers were in that tail, and the row that superseded it (one sentence
    # earlier, and the sentence both wordings share) now owns the construct.
    # Kept rather than deleted so the table can still read a pre-2026-10-01
    # log, which is an artifact the sweep tool has no reason to keep.
    "a slot's declared type is not declared by its struct":
        "SUPERSEDED and 0 files measured: `formal/build.py:2731` reworded the "
        "tail of this message, both of this row's markers were in that tail, "
        "and 'the slot would have to hold a frame address, and no type says "
        "so' now keys on the sentence the two wordings share. Its old wording "
        "is still exercised, as a sample of THAT row",
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

    # The bracketed-specialization row and the callee row are about the SAME
    # callee, and `formal/model.py` grew the second message as a sibling of the
    # first. They share no substring today, so neither order is load-bearing —
    # and a refactor that made them share one would be silent about which row
    # lost. Both directions are stated, with the message each way, because the
    # cost of getting this wrong is the 93-file row being counted as the
    # 28-file one.
    bracket = ("debug_assert[…](…) calls a name this unit does not compile, so "
               "the brackets cannot be bound")
    if C.classify_message(bracket) != (
            "a bracketed specialization of a callee this unit does not "
            "compile"):
        failures.append(
            "the bracketed-specialization cause is being shadowed; its row is "
            "the largest in the sweep and it must classify to itself, not to a "
            f"neighbouring callee row (got {C.classify_message(bracket)!r})")
    plain = ("a X receiver is passed to foo(), which is a name with no "
             "definition in hand IN THIS IMAGE")
    if C.classify_message(plain) != "callee has no definition on this path":
        failures.append(
            "the 'callee has no definition' cause is now being shadowed BY the "
            "bracketed-specialization one; adding a cause below it must not "
            f"steal its row (got {C.classify_message(plain)!r})")

    # The field-store row is a SIBLING of the container row, not an
    # alternative: `formal/build.py` emits different wording for each, and the
    # two say different things (a field has an owner that outlives the call).
    # Asserted separately so merging them cannot happen unnoticed.
    for msg, want in (
            ("a Optional receiver is stored in a container, which has no layout "
             "for a frame address on this path", "receiver stored in a container"),
            ("a Optional receiver is stored in the field 'self.start', so it "
             "outlives the frame it names",
             "receiver stored in a field of a struct that outlives it")):
        if C.classify_message(msg) != want:
            failures.append(
                f"the container/field frame-store pair collapsed: expected "
                f"{want!r}, got {C.classify_message(msg)!r}. They are two "
                "constructs — a container has no owner, a field outlives the "
                "call — and a merge would hide which one a file is blocked by")


def main() -> int:
    failures = []
    checks = len(SAMPLES) + 3

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
    # `+ 4` is the number of assertions `main` makes about the FAMILY table
    # below (precedence, the catch-all's absence, one per marker). It is
    # written as a literal because these are counted by hand, which is exactly
    # how a tally starts lying: an assertion added to `check_cause_table` and
    # not counted here is a check that cannot fail the run in anyone's reading
    # of the number. Anything added to either function needs its count bumped.
    checks = (len(SAMPLES) + 3 + len(CAUSE_SAMPLES) + len(C.CAUSES) + 4 + 4)
    # …and the `uses:` column's own audit, which counts its checks into the
    # same total rather than printing a second tally.
    checks += _uses_column_checks(failures)
    print(f"\nrefusal taxonomy: {'PASS' if not failures else 'FAIL'} "
          f"({checks - len(failures)}/{checks} checks, "
          f"{len(set(names))} families, {len(C.CAUSES)} causes)")
    return 1 if failures else 0


# ── the `uses:` column of the CAUSE table, and the audit it rests on ─────────
#
# The same discipline the family table above is held to, applied to the number
# the cause table ranks by. `FILES BLOCKED` is an upper bound; for a cause about
# a module's boundary the question "how many of these files would a fix to THAT
# MODULE actually reach" has a cheap exact answer when the files name none of
# its declarations, and it is not the count.
#
# The cause table is reached as `formal_sweep_causes`, whose source index is a
# module global built by walking both trees; the tests below pin it to four
# fixture files, because "the number is 0 because it could not look" and "the
# number is 0 because it looked and found nothing" have to be told apart.

# The real wording `no_public_api_reason` emits for a generic struct template.
_MODULE_REFUSAL = ("template.mojo: formal dylib has no public functions: "
                   "template.mojo exports nothing under doc/ABI.md's rules: it "
                   "declares only the generic struct template(s) Thing, and a "
                   "parametric type has no single boundary layout either.")


def _uses_column_checks(failures):
    import formal_sweep_causes as C
    n = [0]

    def check(ok, message):
        n[0] += 1
        if not ok:
            failures.append(message)

    tmp = tempfile.mkdtemp(prefix="uses_column_")

    def write(name, text):
        path = os.path.join(tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    module = write("template.mojo",
                   "struct Thing[T: Copyable]:\n  var x: Int\n")
    uses_it = write("uses_it.mojo",
                    "from template import Thing\nvar h = Thing[Int]()\n")
    does_not = write("does_not.mojo",
                     "from something_else import Widget\nvar w = Widget()\n")
    # Its only `Thing` is inside `ThingHelper`, so a substring match counts it.
    longer = write("longer_name.mojo",
                   "from template import ThingHelper\nvar q = ThingHelper()\n")

    def line(path, refuser):
        return (f"CODEGEN/DEPENDENCY: {path}  (build: a.mojo imports 'x', which "
                f"cannot be built either: {refuser}: {_MODULE_REFUSAL})")

    def rank(log, index):
        saved = C._index
        C._index = index
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".log",
                                             delete=False) as f:
                f.write(log)
                logpath = f.name
            try:
                return C.rank(logpath)[0]
            finally:
                os.unlink(logpath)
        finally:
            C._index = saved

    def row_of(table, cause):
        for r in table:
            if r["cause"] == cause:
                return r
        return None

    table = rank("\n".join([line(uses_it, "template.mojo"),
                            line(does_not, "template.mojo"),
                            line(longer, "template.mojo")]) + "\n",
                 {"template.mojo": [module]})
    row = row_of(table, C.CAUSE_NO_BOUNDARY_SYMBOL)
    check(row is not None,
          "a real `module exports no public functions` message was not "
          "classified as one, so the cause table no longer recognises the "
          f"wording it was written for. Labels seen: "
          f"{[r['cause'] for r in table]}")
    if row is None or len(row["uses"]) != 1:
        check(False,
              f"three findings from one refusing module produced "
              f"{0 if row is None else len(row['uses'])} `uses:` entries")
        return n[0]
    refuser, src, blocks, uses, declared = row["uses"][0]
    check(blocks == 3, f"expected 3 blocked files, got {blocks}")
    check(src == module,
          f"the refusing module resolved to {src!r}, not the fixture "
          f"{module!r} — the index lookup is not returning the file it was "
          f"handed")
    check(declared == ["Thing"],
          f"the declared names are {declared}, expected ['Thing'] — the column "
          f"is searching for the wrong population")
    # One use, and `longer.mojo` is not one: a plain substring match would
    # report 2, and 0 would make every row read as closure.
    check(uses == 1,
          f"`uses` counted {uses} of 3. It must count `uses_it.mojo` alone — "
          f"0 makes every row read as closure, and a substring match also "
          f"counts `longer_name.mojo`, whose only `Thing` is inside "
          f"`ThingHelper`")

    gone = row_of(rank(line(does_not, "gone.mojo") + "\n", {}),
                  C.CAUSE_NO_BOUNDARY_SYMBOL)
    check(gone is not None and len(gone["uses"]) == 1,
          "a refusal from a module that is not on disk produced no `uses:` "
          "entry, so there is nowhere for the not-measured note to live")
    if gone is not None and gone["uses"]:
        check(gone["uses"][0][1] is None,
              f"a refusing module absent from the tree resolved to "
              f"{gone['uses'][0][1]!r} instead of None, so its 0 would be "
              f"printed as a measurement")

    def resolve(basename, index):
        saved = C._index
        C._index = index
        try:
            return C._resolve_refuser(basename, does_not)
        finally:
            C._index = saved

    one = write("dup_a/__init__.mojo", "struct Other:\n  var y: Int\n")
    two = write("dup_b/__init__.mojo", "struct Other:\n  var y: Int\n")
    got = resolve("__init__.mojo", {"__init__.mojo": [one, two]})
    check(got is None,
          f"an ambiguous basename resolved to {got!r}; a count computed from "
          f"the wrong one of two files is a number nobody can check")
    solo = resolve("template.mojo", {"template.mojo": [module]})
    check(solo == module,
          f"an unambiguous basename resolved to {solo!r}, so the ambiguity "
          f"guard would pass for the wrong reason")

    # The audit the whole 38-file row rests on, which nothing pinned before.
    heap = None
    try:
        import module_loader
        cand = os.path.join(module_loader.STDLIB_PATH,
                            "std", "collections", "binary_heap.mojo")
        heap = cand if os.path.isfile(cand) else None
    except Exception:                                    # noqa: BLE001
        heap = None
    if heap is None:
        print("  SKIP  the stdlib is not reachable from here, so the "
              "binary_heap.mojo export audit is not checked")
    else:
        import reflect
        with open(heap, encoding="utf-8", errors="replace") as f:
            excl = reflect.export_exclusions(f.read())
        check(excl == {"BinaryHeap": "generic-template"},
              f"std/collections/binary_heap.mojo's export exclusions are "
              f"{excl}, not {{'BinaryHeap': 'generic-template'}}. "
              f"FORMAL_known_limits.md §1.1a and the 38-file row both rest on "
              f"that being the whole story: if it changed, the row is a "
              f"different finding and the doc is wrong, and both need "
              f"re-auditing rather than a stale number standing in for them")
    return n[0]


if __name__ == "__main__":
    sys.exit(main())
