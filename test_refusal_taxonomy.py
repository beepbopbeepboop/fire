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

3. **A marker for a message the backend can no longer produce is rot with a
   sample attached to it.** The family "a module whose API is its top-level
   statements, imported by another" and its sample were removed on
   2026-10-03 with the dylib-module-body row it keyed on (§6 of
   `bugs/FORMAL_sweep_work_map_2026-10-02_b7.md`, whose doc was deleted with
   the fix): both object writers emit a load-time initializer, so the refusal
   that named it no longer exists and a sample of a message nothing produces is
   a sample that can only rot. A family is removed when its message stops being
   reachable, and the test that says so is this file's list — the absence of a
   row is the only record that the message is gone.

4. **A count that reads like a gap and is not one.** The cause table in
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
    # The container-operand family: a container operation whose base is a word
    # ESTABLISHED not to be a container.  Three rows because the BASE is what
    # tells a reader which of them to look at, and because the field row is new
    # (`model.slot_container_operand_refusal`) — the two others were already
    # being filed as "other refusal", which is the thing this table exists to
    # prevent.  Each sample is the opening clause of a real message.
    ("container operation on a scalar slot",
     "a subscript of `s.n` asks for a container element, and `s.n` is a struct "
     "field declared to hold an integer"),
    ("container operation on a non-container",
     "a subscript of `a` asks for a container element, and `a` is a value this "
     "function bound to an integer"),
    ("container operation on a frame address",
     "xs is a CONTAINER operation on a Opt FRAME ADDRESS, and a frame is not a "
     "container"),
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
    #
    # The OPERATION sample is quoted from the message that REPLACED one fixed
    # sentence for all 104 dialect operations: `mlir_dialect_op_refusal` names
    # the operation and what it denotes rather than asserting that "an MLIR
    # operation has no representation in a 64-bit word", which was false of the
    # elementwise arithmetic subset. It is a separate row rather than a variant
    # because the family here is about SHAPE and the three operation wordings
    # share it — and because the old wording is still live for a caller with no
    # operation in hand, which is the fourth sample.
    ("MLIR construct",
     "materialize: `pop.add` is a dialect OPERATION applied ELEMENTWISE, so "
     "whether it denotes one 64-bit word"),
    # The PREFIX wording, which is what a call site that knows only the
    # `__mlir_` name says. Kept because it is still reachable and still a true
    # statement about what is missing for the family, and because a sample that
    # quotes only the classified wordings would let the prefix row rot silently.
    ("MLIR construct",
     "materialize: __mlir_op is an MLIR dialect construct: this path has no "
     "MLIR, so it lowers a Mojo program to a Mach-O image"),
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
    # A one-field struct's MUTATING method, whose receiver is the struct, so the
    # callee hands the receiver back and the caller has to store it. FOUR
    # wordings, one family, and all four are here because `classify_message`
    # sees only the message: a marker added for a wording no sample exercised
    # is the dead-marker failure this file exists for, and these four are the
    # only four that mechanism refuses.
    #
    # **All four re-pointed 2026-10-03** with the mechanism underneath them: the
    # receiver is handed over BY REFERENCE now (`model.receiver_writeback_name`),
    # which is what removed the refusal that used to be this family's headline
    # — `Cell.bump() both changes its receiver and returns a value`, i.e.
    # `BinaryHeap.pop()`. A sample whose wording no build emits any more would
    # keep passing (the marker is still in the table) while measuring a construct
    # that does not exist, so the samples are the point rather than the formality.
    ("one-field mutator receiver hand-off",
     "Cell.bump() changes its receiver and declares no return type, so the "
     "call has no value, and it is used as one here"),
    ("one-field mutator receiver hand-off",
     "Cell.bump() is a one-field struct's mutating method, so the value it "
     "computed has to be stored back through the receiver's own storage, "
     "which means the caller has to hand it the ADDRESS of that storage. "
     "items[0] is not a place this path can take the address of"),
    ("one-field mutator receiver hand-off",
     "Cell.pop() is called in the same argument list that reads c, the "
     "receiver it changes"),
    ("one-field mutator receiver hand-off",
     "Cell.swap() changes its receiver and returns a frame, and this path has "
     "two hidden-word conventions"),
    # ── a call through a VALUE, 2026-10-03. The construct itself LOWERS now
    #    (a function value is a code address and the specialization's brackets
    #    are leading arguments), so what is in this bucket is the three shapes
    #    with NO declaration in hand — three rows rather than one because the
    #    three fixes are different, which is the whole criterion this table is
    #    keyed on. One cause and one sample each: `classify_message` sees only
    #    the message, so a marker with no sample is the dead-marker failure.
    ("value call: declared type cannot hold a function",
     "`f` is a call through a VALUE rather than through a function of this "
     "unit — `f` is a name call_container binds, a parameter or a local of it "
     "and it is declared `List[Int]`, and a word that is not a code address "
     "is nothing to branch through"),
    ("value call: bracket unreadable",
     "`workgroup_function[…](…)` is a bracketed call through a VALUE, and a "
     "bracket on a value is two constructs: the comptime parameters of a "
     "specialization, or an index into a container"),
    ("value call: keyword unreadable",
     "`f(x, b=2)` is a keyword argument in a call through a VALUE, and this "
     "path has no declaration to bind it by NAME: a callee reached through a "
     "word is read as taking the arguments the call site writes"),
    # The PASSING end rather than the calling end, and a different family
    # because the fix is in a different place: a value call's refusal is raised
    # by an emitter (there is no declaration to read at the call site), this one
    # by `formal/build.py`'s name-placement walk, which is the only pass that
    # has both ends of the call at once.
    ("function value into a declared non-function",
     "'dbl' is a FUNCTION of this image read as a value, and it is passed to "
     "`call2()` in main as parameter `f`, which is declared `Int`"),

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
    # The OPERATION wording, which replaced the one fixed sentence that named
    # the `__mlir_` PREFIX. `formal/model.py`'s `mlir_dialect_op_refusal` now
    # classifies the operation by what it DENOTES — an effect, an elementwise
    # arithmetic result, or a value needing a fact this path lacks — so three
    # different messages carry this clause and each needs its own sample for the
    # reason the type spelling above does: `classify_message` sees only the
    # message, so one sample is one proof its marker matches.
    #
    # The first is the EFFECT (`std/sys/debug.mojo:20`, verbatim), the second is
    # ELEMENTWISE arithmetic (`std/simd.mojo:1082`), and the third is a value
    # that cannot be GUARDED without its bracketed predicate (`std/simd.mojo:
    # 1546`). All three are quoted from the live text, so a later reword of any
    # of them fails this row rather than silently emptying the cause.
    ("MLIR dialect construct (__mlir_attr / __mlir_type / __mlir_op)",
     "_select_register_value: `pop.add` is a dialect OPERATION applied "
     "ELEMENTWISE, so whether it denotes one 64-bit word"),
    ("MLIR dialect construct (__mlir_attr / __mlir_type / __mlir_op)",
     "debugtrap: `llvm.intr.debugtrap` is a dialect OPERATION and denotes NO "
     "VALUE: it is an EFFECT"),
    ("MLIR dialect construct (__mlir_attr / __mlir_type / __mlir_op)",
     "eq: `pop.cmp` is a dialect OPERATION whose value could be a word on this "
     "path, but it cannot be GUARDED here"),
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
    # A `try` handler arm with a body. This is the refusal that appeared for 5
    # files when the dylib-module-body row was closed, and it is CORRECT by
    # design — `formal` has no unwinder, so an arm's body cannot be in the image
    # and dropping it silently would be a wrong-but-exit-0 answer. It is in the
    # taxonomy because "refused on purpose" and "nobody has looked" are
    # different answers, and `other refusal` cannot tell them apart.
    ("a handler arm with a body (no unwinder to emit it into)",
     "memslot.py: line 407: `ValueError` as e is a handler arm with a body "
     "this path cannot put in the image, so it is refused rather than "
     "dropped: `formal` has no exception unwinder, so no edge runs from a "
     "raise site into an arm"),
    # The ORDER half. Cut from `model.module_slot_unreadable_refusal` rather    # The ORDER half. Cut from `model.module_slot_unreadable_refusal` rather
    # than from a sweep log, because the shape it refuses did not exist as a
    # distinct message until a module body was recognised as the module's own
    # writer — before that, a name whose value a call computes and a name read
    # before its slot was filled were the same refusal, and this sample would
    # have been indistinguishable from the row above.
    ("a module global the module BODY fills, read before it fills it",
     "read_g: 'G' is one of the module-global slots in this image's `__DATA`, "
     "and it has no static initializer: the value is computed by the module's "
     "own top-level statements, which this path compiles into the synthetic "
     "function the startup stub enters. That function is the entry, so nothing "
     "runs before its first statement — but this read is reached before the "
     "store of 'G' completes, so the load would read the zero an unwritten slot "
     "gives. The module body calls something at its statement 1, before it "
     "reaches the assignment at statement 2 that fills 'G'. Move the assignment "
     "above the first top-level statement that calls anything. Make the value a "
     "literal and the build folds it at every read instead"),
    ("a module-level name of ANOTHER module is not exported as a word",
     "main: 'sys' is imported from `sys`, and it is a module-level name of "
     "another module. This path compiles an import into a dylib"),
    # The DOTTED spelling, and a separate sample rather than a variant of the
    # one above: the bare message blames the NAME for having no storage, which
    # is true of a name and false of a module. The two rows key on clauses only
    # their own message contains, so neither can swallow the other — see the
    # comment on the two CAUSES entries in tools/formal_sweep_causes.py.
    ("a module's ATTRIBUTE read as a value, across a dylib boundary",
     "main: sys.argv reads 'argv' out of the imported module `sys`, and a "
     "module is not a value this path can place"),
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
    # The corpus's LARGEST row, and it had no row at all until 2026-10-04: 170 of
    # the 710 files on the b10 sweep, 55% of every codegen finding in the tree,
    # every one of them this one sentence. The ranking reported them as
    # `other refusal` — the bucket `tools/formal_sweep_causes.py`'s own docstring
    # defines as "nobody has looked" — which is the defect §5 of
    # `bugs/FORMAL_sweep_work_map_2026-10-04_b10.md` is about.
    #
    # TWO samples, not one, because `classify_message` sees only the message and
    # one sample is one proof its marker matches. They are the row's two ends: the
    # stdlib's own `FormatStruct(writer, "Allocation")` (111 of the 170) and a
    # repository file's `now()` through `time`. Both are cut from
    # `formal/model.py::imported_callee_refusal`'s f-string rather than from a
    # sweep log, so a reword of that f-string has to be made here too rather than
    # leaving a sample of a sentence nothing emits.
    #
    # The marker deliberately is NOT the sentence that used to follow these two
    # clauses. "spell it as `name[<a type>](…)`" is ADVICE, and `work/formal19-1`
    # deletes it because it is wrong about correct Mojo — a bare template call is
    # the spelling the stdlib uses — so a marker keyed on it would have taken 170
    # files silently back to `other refusal` the day that branch landed. What is
    # left is the FACT: the call has to bind a symbol the module does not export.
    ("a call to a name the defining module does not export",
     "`FormatStruct` is called, and it is imported from `std.format._utils`, so "
     "the call has to bind a symbol `std.format._utils` exports. That module does "
     "not export it, and the reason is `doc/ABI.md`'s export rule rather than "
     "anything about this call: a name with a leading `_` is private, a generic "
     "template is not one symbol but one per instantiation"),
    ("a call to a name the defining module does not export",
     "main: `now` is called, and it is imported from `time`, so the call has to "
     "bind a symbol `time` exports. That module does not export it, and the reason "
     "is `doc/ABI.md`'s export rule rather than anything about this call: a name "
     "with a leading `_` is private, a generic template is not one symbol but one "
     "per instantiation"),
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
    # from) and it classifies
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
    # A REAL message, not a constructed one: `test_llm/dumb_gemm.mojo` is
    # `[0.0] * (m * k)` three times over, and it is the file whose
    # "print() cannot classify" row this replaced. Pinned here so a rewording
    # of the repetition refusal cannot quietly move it back into
    # `other refusal`, which is what the marker in
    # `tools/formal_sweep_causes.py` exists to prevent.
    ("a repetition whose count this path cannot read",
     "[FloatLiteral] * m * k is a REPETITION, and this path can only lower "
     "one whose count it can read while emitting"),
    ("len() of a value that has no length",
     "len(s) is len() of a value classified as 'int', and an integer has no "
     "length"),
    # A `with` whose context this build cannot type, cut from
    # `formal/model.py::refuse_unlowerable_with` (the "not a construction of a
    # struct this image compiles" arm) rather than from a sweep log, because the
    # construct is the most common statement in this repository's own files
    # (`with open(` is in 192 of them) and the message names the protocol it
    # cannot honour rather than the value it cannot type. The sample is the
    # `open` spelling on purpose: it is the one a reader meets first, and it is
    # the one the resource table now answers.
    ("a `with` over a value this build cannot type",
     "ModuleLoader_load_module_from_path: `with open(path, 'r') as …` is "
     "CPython's CONTEXT-MANAGER PROTOCOL — `type(mgr).__enter__` binds the "
     "name, and `type(mgr).__exit__` runs on the way out — and this path "
     "cannot honour it here: this build cannot answer what type it is, "
     "because it is not a construction of a struct this image compiles"),
    # …and the ALIAS half, which is the same construct and used to be reported
    # with the message above — a message that describes the context expression,
    # which is FINE in this case, so the reader was sent to the wrong half of
    # their own line.  Its own sample because
    # `formal/model.py::refuse_unlowerable_with_alias` opens with the protocol
    # sentence on purpose: one row, so a file refused for the alias shape is
    # counted beside one refused for the context, and the sentence that says why
    # is the part that differs.
    ("a `with` over a value this build cannot type",
     "load_pair: `with … as …` is CPython's CONTEXT-MANAGER PROTOCOL — "
     "`type(mgr).__enter__` binds the name — and this `as` clause names "
     "somewhere this path cannot put the word `__enter__` returns: a formal "
     "value is one 64-bit word, and a destructuring target or a store into "
     "`obj.attr` is not a place one word goes"),
    ("a method on a multi-field struct where a descriptor is meant",
     "writer.write_string() is a method on a Writer — a multi-field struct, so "
     "on this path the receiver is the ADDRESS of a frame"),
    # FOUR samples for one cause, because the message has been reworded once and
    # a classifier that only knows the current wording stops seeing every sweep
    # log ever taken — which is the failure this file exists to catch, in the
    # direction that actually happens.
    #
    # The first two are the REGISTER-count wording, both real messages from the
    # 2026-10-01 r2 logs, one per architecture: both backends build the sentence
    # from one f-string with their own constant (`_ABI_ARG_REGS` = 8,
    # `len(ARG_REGS)` = 6), so a table that only knew the arm64 number read 57
    # x86-64 files as unclassified.
    #
    # The last two are the FRAME-BUDGET wording that replaced it on 2026-10-02,
    # when both ABIs grew their stack-argument convention: the ceiling is now 24
    # on both machines and the register counts are the REGISTER half of a split.
    # Keeping the old two is not sentiment — the dated work-map tables in
    # `bugs/` are written against logs that carry the old wording, and a sweep
    # re-read tomorrow has to classify them the same way.
    ("too many parameters for the register ABI (8 on arm64, 6 on x86-64)",
     "_build_segment_64: 9 parameters exceeds the 8 the formal arm64 ABI "
     "passes in registers"),
    ("too many parameters for the register ABI (8 on arm64, 6 on x86-64)",
     "b2_g: 7 parameters exceeds the 6 the formal x86-64 ABI passes in "
     "registers"),
    ("too many parameters for the register ABI (8 on arm64, 6 on x86-64)",
     "_build_segment_64: 25 parameters exceeds the 24 the formal arm64 ABI "
     "passes (8 in registers and 16 on the stack)"),
    ("too many parameters for the register ABI (8 on arm64, 6 on x86-64)",
     "wide: 25 arguments exceeds the 24 the formal x86-64 ABI passes "
     "(6 in registers and 18 on the stack)"),
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
    ("a field the struct does not declare (missing, or a comptime member)",
     "res._InjectedValues is a field of res, and _ZipIterator has no field "
     "'_InjectedValues': its 2 field(s): origin, _values"),
    ("a field the struct does not declare (missing, or a comptime member)",
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
     "constructing A5b with arguments is a call to a user-defined `__init__` "
     "whose body this path does not inline: a read of the receiver this path "
     "cannot resolve against the block being constructed: `self.a` handed to "
     "`twice5(…)` as an argument"),
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
    # A one-field struct's mutating method: the receiver IS the struct, so the
    # callee has to hand the receiver back somehow. ONE cause with four wordings
    # in the FAMILY table above; this sample proves the CAUSE table's marker for
    # the wordings the FAMILY table samples do NOT cover — the two tables have
    # different markers and therefore different rot, which is the whole reason
    # there are two tables. The four alternatives in `CAUSES` are one per
    # wording; the first is the one exercised here.
    ("a one-field mutator's receiver hand-off is refused",
     "Cell.bump() changes its receiver and declares no return type, so the "
     "call has no value, and it is used as one here"),
    # The same three, in the PLANNER's table, which has its own markers and
    # therefore its own rot. The bracket one is quoted from
    # `std/algorithm/backend/tile.mojo`'s own spelling (`workgroup_function`),
    # because that is the file the row is about and a sample from a test
    # program would let a reword of the test's own text go unnoticed.
    ("a call through a value whose declared type cannot hold one",
     "`func` is a call through a VALUE rather than through a function of this "
     "unit — `func` is a name call_container binds, a parameter or a local "
     "of it and it is declared `List[Int]`, and a word that is not a code "
     "address is nothing to branch through"),
    ("a bracketed callee through a value, which this build cannot read",
     "`workgroup_function[…](…)` is a bracketed call through a VALUE, and a "
     "bracket on a value is two constructs: the comptime parameters of a "
     "specialization, or an index into a container"),
    ("a keyword argument in a call through a value",
     "`func(x, b=2)` is a keyword argument in a call through a VALUE, and "
     "this path has no declaration to bind it by NAME: a callee reached "
     "through a word is read as taking the arguments the call site writes"),
    # …and the passing end. Its marker has TWO clauses on purpose: "is passed
    # to" alone is the catch-all two rows below claim, and "read as a value"
    # alone would be matched by any other message that says it, so the pair is
    # what makes this row specific. Quoted from `test_formal_run.py`'s
    # `a_function_name_passed_as_an_argument_is_named_as_one`, which is the case
    # that raised it.
    ("a function passed where the callee declares something else",
     "'dbl' is a FUNCTION of this image read as a value, and it is passed to "
     "`call2()` in main as parameter `f`, which is declared `Int`"),
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


def _no_def_callee_arm_checks(failures):
    """EVERY arm of `frame_undefined_callee_refusal` keeps the clause, and every
    arm classifies as the one family in BOTH tables.

    The row this rests on is `bugs/FORMAL_callee_no_def_ceiling_zero.md`: the
    fifth branch of `frame_receiver_escape_refusal` used to be one sentence over
    five different facts, four of them false of the program in front of the
    reader, and splitting it into one arm per fact meant the arms had to stay
    distinguishable. They are told apart by their tail; what keeps them in the
    SAME family is the clause they all open with.

    That clause is load-bearing and nothing tested it. Two taxonomies key on the
    exact substring — `tools/formal_sweep.py`'s `_FRAME_ESCAPES` and
    `tools/formal_sweep_causes.py`'s `callee has no definition on this path` —
    and the message itself begins `a X receiver is passed to …`, which is the
    `receiver passed as an argument` family's own opening. So an arm that
    reworded its opening would fall into whichever family matches next, with a
    wrong number in a table a planner acts on and no test failing. It already
    happened: the first version of the split had four arms that did not keep it.

    So this asks the question at the SOURCE rather than at a sample: one callee
    per arm, taken from the arm's own condition, and three assertions each --
    the clause is there, the family is the same in both tables, and the texts are
    pairwise DISTINCT (a shared text would be the pre-split defect returning, and
    it would pass the first two assertions).

    The arms, and the fact that selects each: a compile-time reflection
    intrinsic, a builtin with no implementation (`UNIMPLEMENTED_BUILTINS`, added
    after the document's five), a compile-time parameter, a name bound by a
    `from … import …`, a name reachable only through a star import, and nothing
    at all. `struct_names` is passed for all six because a frame receiver is what
    makes the sentence about a receiver at all.
    """
    sys.path.insert(0, HERE)
    from formal.model import frame_undefined_callee_refusal
    clause = "which is a name with no definition in hand"
    family = "callee has no definition on this path"
    arms = [
        ("reflection intrinsic", "__get_mvalue_as_litref", {}),
        ("unimplemented builtin", "getattr", {}),
        ("compile-time parameter", "Fn",
         {"comptime_param_of": "drive"}),
        ("imported free function", "_b64encode",
         {"imported_from": "._b64encode"}),
        ("star import", "assert_true",
         {"star_imported_from": "lib"}),
        ("genuinely unbound", "mojo_print", {}),
    ]
    texts = {}
    for label, callee, kwargs in arms:
        msg = frame_undefined_callee_refusal(callee, ["P"], **kwargs)
        if msg is None:
            failures.append(
                f"the {label} arm returned None for {callee!r}; the caller "
                "cannot distinguish 'this construct is fine' from 'this arm is "
                "unreachable'")
            continue
        texts[label] = msg
        if clause not in msg:
            failures.append(
                f"the {label} arm does not carry {clause!r}. Two taxonomies key "
                f"on that substring and the message begins 'a X receiver is "
                f"passed to …', which is the receiver family's own opening, so "
                f"this arm's files would be counted as receiver problems: "
                f"{msg[:120]}")
        for tool, got in (("formal_sweep", S._refusal_family(msg)),
                          ("formal_sweep_causes", C.classify_message(msg))):
            if got != family:
                failures.append(
                    f"{tool} classifies the {label} arm as {got!r}, not "
                    f"{family!r}")
    seen = {}
    for label, msg in texts.items():
        for other, prev in seen.items():
            if msg == prev:
                failures.append(
                    f"the {label} arm and the {other} arm emit the SAME text, "
                    "so the split that gives each its own reason has collapsed "
                    "back to one sentence over two facts")
        seen[label] = msg
    return len(arms) * 3 + len(texts) - len(set(texts.values()))


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
    # …and the six-arm census of `frame_undefined_callee_refusal`, whose clause
    # both tables key on and which nothing tested.
    checks += _no_def_callee_arm_checks(failures)
    # …and the host-import row's rank audit: every host module ranked by which
    # sweep files actually import it, so the table cannot claim a reach the
    # corpus does not have.
    checks += _host_rank_checks(failures)
    # The failures are printed AFTER every group has run, and that ordering is
    # the fix rather than the tidiness: the loop used to sit above the three
    # `checks += …` lines, so a failure raised by any of them was counted in
    # the tally below and printed by NOTHING — the run said `FAIL (177/179)`
    # and named none of the checks that failed. A failure a reader cannot see
    # is the same as no check at all.
    for f in failures:
        print("  FAIL  " + f)
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


# ── the HOST row of the same table: ranked by MODULE, not by construct ─────
#
# `tools/formal_sweep_causes.py --host` exists because the cause table above
# cannot rank `not-answerable/host-import` at all: a host-import line is not a
# refusal about a construct, it is a refusal about a MODULE, so the question a
# person asks of that row is "which module" and the whole ranking is by module.
# It is the largest class in the sweep (241 files against 285 codegen lines on
# the 2026-10-02 arm), so "the tool declines to rank it" was the biggest thing
# the instrument was not doing.
#
# EVERYTHING THE CAUSE TABLE GETS WRONG ABOUT ITS OWN `uses:` COLUMN IS WORSE
# HERE, and the checks below are the same discipline applied to the same kind of
# number. A host import blocks every importer of its importers, so the row is
# closure-heavy by construction; and the names it searches for are `copy`,
# `types`, `signal`, `html` and `datetime` — ordinary English words that appear
# in prose, in comments and in the bodies of functions that have nothing to do
# with the module. A word search would report `copy` as used by five files when
# it is used by none, and `0 because it could not look` has to be told apart
# from `0 because it looked` for the same reason it does above.

_HOST_REFUSAL_HOST = ("gimple_codegen.py imports 'zlib', which is a host "
                      "module (CPython standard library), which has no Mojo "
                      "source for this backend to compile")
# A module in NEITHER tier with no model, which is the state this table has to
# be able to REPORT. `bz2` is here rather than `datetime` because `datetime`
# stopped being an example on 2026-10-03 (it was classified `modelled`, with
# the reason, in `formal/imports.py`) — and a check whose subject gets fixed
# has to move to the next one or it fails for a reason nobody reading it can
# see. `bz2` is a library outside libSystem like `zlib` and is in the same
# state, so it is the next example and the premise is asserted below rather
# than trusted: if `bz2` is ever classified, this fails saying so.
_HOST_UNTIERED_NAME = "bz2"
_HOST_REFUSAL_UNTIERED = ("fire.py imports '%s', which is not a stdlib "
                          "or sibling module, and no such file exists"
                          % _HOST_UNTIERED_NAME)
_HOST_CHAIN = ("build: analyze_benchmarks_types.py imports 'gimple_codegen', "
               "which cannot be built either: " + _HOST_REFUSAL_HOST)


def _host_rank_checks(failures):
    """The `--host` table's rows, and the three ways each of its numbers lies."""
    import formal_sweep_causes as C
    n = [0]

    def check(ok, message):
        n[0] += 1
        if not ok:
            failures.append(message)

    tmp = tempfile.mkdtemp(prefix="host_row_")

    def write(name, text):
        path = os.path.join(tmp, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def rank(lines):
        log = os.path.join(tmp, "log.txt")
        with open(log, "w") as f:
            f.write("\n".join(lines) + "\n")
        return C.host_rank(log)

    # Three files behind one module, and each uses it in a DIFFERENT SPELLING,
    # because the three spellings are three ways the `uses` column can be
    # wrong: qualified (`m.copy`), a from-import (`from m import copy`) and a
    # file that mentions the word in a comment and does NOT use it.
    users = write("users_a.mojo", "import copy\nvar x = copy.copy(1)\n")
    importer = write("users_b.mojo",
                     "from copy import copy\nvar x = copy(1)\n")
    prose = write("users_c.mojo",
                  "import copy\n# we make a copy of the tree before we "
                  "build\nvar x = 1\n")

    def line(path, detail):
        return f"NOT-ANSWERABLE/HOST-IMPORT: {path}  (build: {detail})"

    table, nlines, nfiles = rank([
        line(users, _HOST_REFUSAL_HOST),
        line(importer, _HOST_REFUSAL_HOST),
        line(prose, _HOST_REFUSAL_HOST),
        line(write("chain.py", "import gimple_codegen\n"),
             _HOST_CHAIN),
        line(write("untiered.py", "import %s\n" % _HOST_UNTIERED_NAME),
             _HOST_REFUSAL_UNTIERED),
    ])
    rows = {r["module"]: r for r in table}
    check(set(rows) == {"zlib", _HOST_UNTIERED_NAME},
          f"the table ranked {sorted(rows)} and the log names exactly 'zlib' "
          f"(three files plus one behind a CHAIN) and "
          f"{_HOST_UNTIERED_NAME!r}. A row for a module the log never names, "
          f"or a missing row for one it does, is the ranking measuring "
          f"something else")
    z = rows.get("zlib")
    if z is not None:
        check(z["files"] == 4,
              f"zlib blocked {z['files']} files and the log has four lines "
              f"behind it, one of them through a dependency chain. A CHAIN is "
              f"one line whose terminal refusal is the module, so it "
              f"contributes one file")
        # The declared names come from CPython's own source, so they are only
        # known for a module that HAS one. `zlib` is built into the
        # interpreter, so the honest answer is that they could not be read.
        check(z["declared_known"] is False,
              f"zlib's declared names are {z['declared']!r} "
              f"(known={z['declared_known']}). zlib is a BUILT-IN extension "
              f"with no stdlib source, so the only honest answer is None — a "
              f"count computed from a list of names written here would be a "
              f"number nobody can check against anything")
    d = rows.get(_HOST_UNTIERED_NAME)
    if d is not None:
        try:
            from formal import imports as _I
            tier = _I.host_module_tier(_HOST_UNTIERED_NAME)
            have_model = C._host_model_source(_HOST_UNTIERED_NAME) is not None
        except Exception as exc:                         # noqa: BLE001
            check(False, f"formal.imports is not importable here: {exc}")
            tier, have_model = "?", False
        check(tier == "" and not have_model,
              f"precondition: {_HOST_UNTIERED_NAME} is in tier {tier!r} with "
              f"a model at {have_model!r}. It has to be in NEITHER tier with "
              f"no model for this fixture to be the thing it says it is; if it "
              f"has been classified, move _HOST_UNTIERED_NAME to the next "
              f"module in that state rather than deleting the check")
        check(d["untiered"] is True,
              f"{_HOST_UNTIERED_NAME} is in NEITHER formal/imports.py tier "
              f"and has no model, so its refusal reads 'not a stdlib or "
              f"sibling module, and no such file exists' — false of a CPython "
              f"standard-library module. The row has to SAY so "
              f"(untiered={d['untiered']}) or a reader takes the count as a "
              f"work item")
        check(d["model"] is None,
              f"{_HOST_UNTIERED_NAME} reported a model at {d['model']!r}")

    # A module with a model is in no tier BY DESIGN (`HOST_MODELLED`'s rule is
    # "a name LEAVES here by being WRITTEN"), and calling that a defect would
    # report `os` and `sys` as mis-diagnosed.
    try:
        from formal import imports as I
        tier = I.host_module_tier("os")
        model = C._host_model_source("os")
    except Exception as exc:                             # noqa: BLE001
        check(False, f"formal.imports is not importable here: {exc}")
        return n[0]
    check(tier == "" and model is not None,
          f"`os` is in tier {tier!r} with a model at {model!r}. The tier sets "
          f"are for modules with NO source, so `os` in neither tier is the "
          f"rule working, not a gap")
    try:
        import tempfile as _tf
        tid = I.host_module_tier("tempfile")
        tmodel = C._host_model_source("tempfile")
    except Exception:                                    # noqa: BLE001
        tid, tmodel = "?", None
    if tmodel is not None:
        check(tid == "",
              f"`tempfile` has a model at {tmodel!r} and is in tier {tid!r}: a "
              f"name LEAVES the tiers by being WRITTEN, so in neither is "
              f"correct and a table that reported it as UNTIERED would be "
              f"reporting the rule")

    # The `uses` spelling, measured on three fixture files: two real uses in two
    # different spellings, and one file that says the word in a comment.
    try:
        declared = sorted(C._host_declared_names("copy") or ())
    except Exception as exc:                             # noqa: BLE001
        check(False, f"copy's declared names could not be read: {exc}")
        declared = []
    if declared:
        check("copy" in declared and "deepcopy" in declared,
              f"copy's public names are {declared}, and it must contain both "
              f"`copy` and `deepcopy` — they are read out of CPython's own "
              f"source rather than from a list written here, because a list "
              f"would be correct for exactly as long as CPython does not "
              f"change it")
        got = C._host_use_names(users, "copy", declared)
        check(got == {"copy"},
              f"`copy.copy(1)` counted {got!r}, and it must count the "
              f"qualified spelling")
        got = C._host_use_names(importer, "copy", declared)
        check(got == {"copy"},
              f"`from copy import copy` counted {got!r}, and a from-import is "
              f"the second spelling a use can have")
        got = C._host_use_names(prose, "copy", declared)
        check(got == set(),
              f"a file whose only `copy` is inside a COMMENT counted {got!r}. "
              f"This is why the column searches for `mod.NAME` and a "
              f"from-import rather than for the word: `copy`, `types`, "
              f"`signal` and `html` are English words, and a word search "
              f"reports a row as work when it is closure")
    else:
        print("  SKIP  this interpreter's stdlib is not reachable, so the "
              "`uses` spelling checks are not run")

    # A module CPython publishes through `__all__` is ranked on `__all__`, so a
    # name the module has but does not publish cannot make a file look like a
    # user of it.
    try:
        with __import__("tempfile").NamedTemporaryFile() as _f:
            pass
    except Exception:                                    # noqa: BLE001
        pass
    tf_names = C._host_declared_names("tempfile")
    check(tf_names is not None and "mkdtemp" in tf_names
          and not tf_names[0].startswith("_"),
          f"tempfile's public names are {tf_names!r}, and `mkdtemp` is among "
          f"them with no underscore-prefixed name in front")
    return n[0]


if __name__ == "__main__":
    sys.exit(main())
