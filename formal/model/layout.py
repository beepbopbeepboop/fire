from . import *

# ── Aggregate layout ──────────────────────────────────────────────────────
#
# A list/tuple is a blob:  [count:i64][elem0][elem1]…   (8-byte slots)
# A set lowers as a list. A dict is a PAIR blob:
#                            [count:i64][key0][val0][key1][val1]…
# A string is an interned char* with no header.
#
# The count is a PAIR count for a dict, which is why scanning one at the
# element stride only ever reaches the first half of it (slot i of a pair blob
# alternates key, value). `walk_stride` is the rule that keeps a walk over a
# blob — a `for` target, a membership test, a comprehension generator, a `*`
# splice — from making that mistake, and it enumerates those four consumers
# because a consumer it does not name is one nobody audits.

BLOB_HEADER_BYTES = 8      # the i64 count
ELEM_STRIDE = 8            # list element / pair slot stride
BYTE_ELEM_STRIDE = 1       # a BYTE blob's element stride (see `blob_elem_stride`)
PAIR_STRIDE = 16           # key+value pair stride (also the key-address step)
VALUE_OFFSET = 8           # key -> value within a pair


def blob_elem_stride(kind) -> int:
    """Byte step between a blob's own elements, for a blob of value `kind`.

    **The element-width axis, and the reason a byte blob has one.** Every blob
    on this path is `[count:i64][element 0]…` in EIGHT-BYTE slots, which is a
    fact about a formal value (one 64-bit word) rather than about the container:
    a list of words stores a word per slot, and the slot is what makes the
    address arithmetic one shift. A byte blob is the one container whose element
    is narrower than a word, so `bytearray` needs the stride to come from the
    blob's KIND instead of being the constant it has always been.

    `BYTE_BLOB_ELEM_KIND` is the element kind that says "one byte", and this
    function is the only place that maps it to a stride — the two other readers
    of the same kind are `subscript_element_kind` (what `b[i]` YIELDS, which is
    an integer) and `blob_ctor_elem_stride` (how wide a slot a constructor
    reserves). Three questions, one name, because a byte blob whose `len` reads
    one stride while its subscript reads another is a wrong answer with a right
    count in it.

    `BYTE_ELEM_STRIDE` is a power of two precisely so `walk_shift` stays exact
    below; the shift it yields is **0**, and an emitter that scales an index by
    a shift has to notice that `<< 0` is "add", not "emit the same shift you
    always emit".
    """
    if is_byte_blob_kind(kind):
        return BYTE_ELEM_STRIDE
    return ELEM_STRIDE


def walk_stride(is_dict: bool, elem_stride: int = ELEM_STRIDE) -> int:
    """Byte step between the things a walk over a blob YIELDS.

    One word per COUNT for a list, one KEY per COUNT for a dict — so a dict is
    a pair blob and a walk over it steps by the pair.  At the element stride a
    walk alternates keys and values, which is wrong in two ways at once: it
    binds half the values, and bounded by the pair count it can only ever see
    half the dict.  Every walk that yields ONE THING per count asks this; the
    emitters that also want the address of pair `i`'s VALUE want
    `pair_value_offset` and are not asking this question.
`elem_stride` is the blob's OWN element stride (`blob_elem_stride`), which
    is `ELEM_STRIDE` for every blob but a byte one. A dict is a pair blob in
    both cases and its stride ignores the argument, which is why the default
    keeps every existing caller correct: a caller with no kind in hand reads a
    word per element, which is what every blob but a byte one holds.

    **There are FOUR consumers, and the list used to name two of them**, which is
    the whole reason the other two drifted: a `for x in …` target, a `x in …`
    membership needle, a comprehension generator's iterable, and a `*` splice's
    operand.  The last two were hardcoded to the element stride on BOTH
    backends while this function and both `for`-in walkers read it, so
    `[k for k in d]` and `[*d]` built `[k0, v0, k1]` and exited 0 — and the
    COUNT of the result was right, because three PAIRS and three WORDS are the
    same number, so a measurement that looked only at `len` agreed with CPython
    on the buggy programs.  The finding and its four sites are
    `bugs/FORMAL_fuzz_ledger.md` §3.10.  So this docstring enumerating its
    consumers is load-bearing rather than decorative: a consumer not named here
    is a consumer that will not be audited.
    """
    return PAIR_STRIDE if is_dict else elem_stride


def walk_shift(is_dict: bool, elem_stride: int = ELEM_STRIDE) -> int:
    """`walk_stride` as the SHIFT an emitter that scales an index uses.

    `index << walk_shift(is_dict)` is the byte offset the walk advances per
    step, and both strides are powers of two, so the shift is exact rather
    than rounded.  This is the same rule in the unit an instruction encodes it
    (`LSL #3` / `LSL #4`, `SHL $3` / `SHL $4`) and it lives beside the strides
    so the two cannot drift.

    **0 is a real answer here** — `BYTE_ELEM_STRIDE` is 1 — and an emitter
    that hands the shift to a shift instruction emits a no-op that costs an
    instruction; one that selects an encoder by the shift must select the
    ADD. Neither is a detail: `x86_64_codegen`'s `_emit_elem_addr` takes a
    `scale` and shifts by it unconditionally, which is correct at 0, while
    arm64's walks select `LSL #3` by comparison and have to learn 0.
    """
    return walk_stride(is_dict, elem_stride).bit_length() - 1


def element_offset(index: int) -> int:
    """Byte offset of element `index` from a blob's base."""
    return BLOB_HEADER_BYTES + ELEM_STRIDE * index


def pair_key_offset(index: int) -> int:
    """Byte offset of pair `index`'s KEY from a pair blob's base."""
    return BLOB_HEADER_BYTES + PAIR_STRIDE * index


def pair_value_offset(index: int) -> int:
    """Byte offset of pair `index`'s VALUE from a pair blob's base."""
    return pair_key_offset(index) + VALUE_OFFSET




# ── Key comparison ────────────────────────────────────────────────────────
#
# Dict keys and list elements are compared as raw 64-bit words, which is
# *value* equality only for canonical values: interned string literals and
# integers. A tuple/list key is a BLOB POINTER, and two equal tuples built at
# two different points in a program are two different addresses — so the raw
# compare misses. When the key is a container literal whose elements are all
# canonical, comparing it element-wise is the only comparison here that means
# "equal tuple". Anything else keeps the raw compare, which is the documented
# behaviour rather than a silently wrong answer.

def static_key_elements(needle):
    """The element expressions of a statically-known container key, or None.

    None means "compare raw" — either the key is not a container literal, or
    one of its elements is computed and so has no canonical value to compare
    against."""
    if not isinstance(needle, (F.TupleExpr, F.ListExpr)):
        return None
    elems = list(needle.elements)
    if not all(isinstance(x, CANONICAL_ELEM_TYPES) for x in elems):
        return None
    return elems


def key_compare_is_structural(needle) -> bool:
    """True when `needle` compares element-wise rather than as a raw word."""
    return static_key_elements(needle) is not None




# ── A subscript with more than one index ──────────────────────────────────
#
# `x[a, b]` parses as a SubscriptExpr whose index is a TUPLE (`TupleExpr`;
# `fire_compiler.py`'s `Parser` builds one for any bracketed comma list, so
# `x[a]` is a plain index and only the comma makes it a tuple). It is NOT a
# two-dimensional subscript, and the corpus says so unambiguously: across the
# 294 stdlib files and every source in this repository there is not one
# instance whose base is a value. Every one names a generic — `SIMD[dtype,
# width]`, `size_of[type, target]`, `UnsafePointer[NoneType, MutAnyOrigin]` —
# is an `external_call["sym", RetType]`, or is an `__mlir_attr[...]` template.
#
# The `external_call` is called out because it was the expensive mistake here,
# and the shape is why: its bracket is the SAME AST node as a generic's, so
# lumping it in with them looked free and cost a 55-file family several waves
# of re-derivation (bugs/FORMAL_known_limits.md §6.2.1). A shared shape is not
# a shared meaning. What the bracket holds is what decides it, and for
# `external_call` it holds a C SYMBOL and a declared return type — see that
# section below, which is not a comptime parameter list and does not need a
# monomorphizer, because the callee is a symbol that already exists rather than
# a template this compiler must emit.
#
# So the readings this construct could have are settled by the source that uses
# it, and none of them is "index a flat buffer at i*stride + j":
#   * a comptime parameter list — what nearly every corpus instance is. Lowering
#     it means resolving the parameter binding, which needs the callee's type
#     table; there is none here, and guessing a value (e.g. claiming
#     `size_of[DType.int]` is 8) would be a fabricated answer.
#   * an MLIR attribute template — what `__mlir_attr[...]` is. Not a value at
#     all on this path.
#   * an `external_call[...]` template application — LOWERED, to a direct call
#     to the C symbol the bracket names. Not a refusal and not a kind; it is
#     asked about in `multi_index_refusal_for` above, which is why this list
#     does not have a row for it.
#   * a dict keyed by tuples — real, and the one case lowered here, by the
#     element-wise key comparison above. It requires a KNOWN DICT base, which
#     only the backend knows; `multi_index_kind` takes that as an argument.
#   * a 2-D index into a flat buffer — needs a row stride. The source never
#     states one, so any stride would be invented.
#
# Therefore every non-dict, non-external_call case is refused, and
# `multi_index_refusal` says which of the above it is so the diagnostic names
# the construct rather than the symptom. The text is deliberately ARCH-FREE:
# arm64 and x86-64 return the same string, so the two architectures cannot
# drift on what a subscript means (see test_formal_run.py's `refuse:` cases,
# which assert they do not).

MULTI_INDEX_MLIR_TEMPLATE = "mlir-template"
MULTI_INDEX_COMPTIME_PARAMS = "comptime-parameters"
MULTI_INDEX_DATA = "data-multi-index"

# The MLIR spelling forms, which take a bracketed TEMPLATE rather than an
# index: the elements are backtick-quoted literal fragments interleaved with
# compile-time sub-expressions, and the whole thing denotes a dialect
# attribute. `__mlir_op` is absent on purpose and is NOT a gap left by that:
# it is a real side-effecting op, lowered as a call (see fire_compiler's
# statement parser), so calling it a template would misdescribe it, and its
# bracket list is MLIR op attributes with `attrs` set, which is a different
# node again. It is refused by the OTHER rule — `mlir_dialect_refusal`, asked
# for any `__mlir_*` name no template rule covers, which is why the two
# refusals are different sentences rather than one: the template reader can
# quote the fragments the reader has to look for, and the dialect reader
# cannot. Both are arch-free and both are asked through the one reader each
# backend uses.
MLIR_TEMPLATE_NAMES = frozenset((
    "__mlir_attr",
    "__mlir_deferred_attr",
    "__mlir_deferred_type",
    "__mlir_type",
))


def is_multi_index(index) -> bool:
    """True when a subscript's index is a bracketed comma list, not one value."""
    return isinstance(index, (F.TupleExpr, F.ListExpr))


def _base_name(obj):
    """The bare name a subscript base spells, or None if it is not a name."""
    if isinstance(obj, F.IdentExpr):
        return obj.name
    return None


MLIR_DIALECT_PREFIX = "__mlir_"

# The two dialect ROOTS the operand-type reader has to recognise by name, split
# out of `MLIR_DIALECT_PREFIX` because the `__mlir_` prefix alone does not
# separate them: a TYPE names a type and an ATTRIBUTE names an attribute, and
# `mlir_cmp_predicate_op` must accept only the latter as a predicate. Both are
# the corpus's own spellings (`__mlir_type.index`, `__mlir_attr.`#…<eq>``).
MLIR_DIALECT_TYPE_PREFIX = "__mlir_type."
# The BARE root, without the dot: a dialect TYPE is spelled
# `__mlir_type.<name>` and a dialect ATTRIBUTE `__mlir_attr.<name>`, and the
# two are told apart by this root rather than by a prefix, because a subscript
# carries both in one bracket.
MLIR_DIALECT_TYPE_ROOT = "__mlir_type"
MLIR_ATTR_ROOT = "__mlir_attr"



# ── A dialect OPERATION, classified by what it DENOTES ──────────────────────
#
# `mlir_dialect_refusal` used to answer every `__mlir_op` with one sentence —
# "this path has no MLIR … an MLIR attribute, type or operation has no
# representation in [a 64-bit word]" — and that sentence asserts a property of
# the TARGET where the property belongs to the OPERATION. Measured over the
# stdlib (`../new-modular`), where that one sentence was false for a quarter of
# the arithmetic operations:
# 259 `__mlir_op` sites over 104 distinct operations in 49 files. Sorted by what
# each one DENOTES, not by what it is called:
#
#   * 14 operations / 76 sites denote NO VALUE at all — an effect. A store, a
#     trap, an ownership marker, a free, a coroutine step. "Has no
#     representation in a word" is a TRUE statement about these, because there
#     is no value to represent.
#   * 12 operations / 38 sites are ELEMENTWISE ARITHMETIC, and here the op name
#     alone does NOT decide whether the result is a word — the OPERAND's type
#     does. `pop.add` at `std/simd.mojo:1082` is documented by its own source
#     as "a new vector whose element at position `i` is computed as
#     `self[i] + rhs[i]`", over `!kgen.simd<LENGTH, DTYPE>`, so its result is an
#     N-LANE VECTOR and not one 64-bit word. Measured over those 38 sites: 26
#     have a vector or mask operand, 9 have a word operand (`__mlir_type.index`,
#     `!kgen.scalar<ui8>`), 3 are pointer arithmetic.
#
# That second count is the correction, and it is what makes a table keyed on the
# op NAME unsafe rather than merely missing: lowering `pop.add(a, b)` to `a + b`
# is right for the 9 and WRONG for the 26 — a scalar add of two vector-typed
# words, which is a plausible-looking number rather than a refusal. So the
# classification here is deliberately NOT "this op denotes a word": it is
# "this op is ELEMENTWISE, and whether its result is a word is a fact about its
# operands, which is the missing piece", which is true of all 38 and actionable
# for all 38. See the bug doc, which records the census this corrects.
#
# Keyed on the WHOLE dialect operation name — `pop.add`, not `add` — because the
# name is the whole of what this table has: `index.add` and `pop.add` are both
# additions in different dialects, and `pop.cmp` cannot be answered at all
# without its bracketed PREDICATE (six distinct `#kgen.cmp_pred<…>` values in
# the corpus), so an entry that ignored the bracket would answer `eq` and `ne`
# the same way — a wrong answer rather than a refusal.
#
# LEAF-MOST on purpose — `os` and `fire_compiler` only, like the rest of this
# module — so arm64 and x86-64 cannot disagree about what a dialect operation
# denotes. That is the same rule `is_mlir_template` and `shift_signedness`
# already follow, and it is why this table is here and not in either emitter.

# An operation that denotes NO VALUE: an effect. Decided by NAME, which is a
# property of the operation rather than of this path, so this is the one
# classification that needs no operand type to be right. Each is an effect in the
# dialect itself — a store has no result, a trap never returns, an ownership
# marker asserts something about a reference — so "no representation in a 64-bit
# word" is TRUE of them and the reader is not sent to rewrite anything.
#
# MEMBERSHIP IS MEASURED, not assumed: these 15 are the operations the stdlib
# corpus uses as a STANDALONE statement at EVERY one of their sites (joining
# continuation lines so a multi-line call is classified on the statement it
# belongs to), which is the strongest statement a corpus can make about an
# operation — every call site discards it. Two entries are there on the same
# evidence rather than on judgement: `kgen.param.assert` and `lit.materialize_into`
# each appear once as a statement whose result nothing reads.
#
# An operation NOT in this table is not thereby an effect: `pop.atomic.rmw` reads
# `var res = __mlir_op.`pop.atomic.rmw`[…]` in `std/atomic/atomic.mojo:326` and
# returns the old value, so it is a value-denoting operation and belongs with the
# unclassified remainder rather than here. That distinction is the reason the
# class is a set of names and not a pattern over the prefix.
MLIR_EFFECT_OPS = frozenset((
    # ownership / lifetime markers: assert something about a reference
    "lit.ownership.mark_initialized", "lit.ownership.mark_destroyed",
    # traps: never return
    "llvm.intr.trap", "llvm.intr.debugtrap", "kgen.param.assert",
    # memory effects: a store and a free have no result
    "pop.store", "pop.fence", "pop.aligned_free", "pop.global_alloc",
    "pop.stack_allocation",
    # coroutine steps
    "co.destroy", "co.await", "co.set_byref_error_result",
    "co.suspend", "co.suspend.end",
    # codegen bookkeeping and inline assembly: both are statements about the
    # BUILD, not computations in the image
    "kgen.codegen.reachable", "lit.materialize_into", "pop.inline_asm",
    "rocdl.raw.ptr.buffer.load.lds",
))

# The EFFECT operations this path LOWERS instead of refusing, and why the
# answer is "as a divergence" rather than "as a trap instruction".
#
# `MLIR_EFFECT_OPS` above is right that these denote no value, and the refusal
# that table feeds was written for exactly that fact — but it was asked at
# every use, and at a use whose value is DISCARDED the question does not arise:
# there is nothing to represent, because nothing reads a result. So the ground
# the refusal stood on ("no representation in a 64-bit word, because there is
# no value to represent") is absent at a statement, and refusing there is an
# OVER-refusal rather than a safety: it costs a whole module for a construct
# that lowers to the one thing this path already emits when control must not
# continue, which is what `raise` lowers to (`_emit_diverge` in each backend,
# and the Darwin `exit(1)` sequence both of those share).
#
# **What this is NOT.** It is not a trap, and it does not stop the machine the
# way `brk`/`int3` would: the source asked for a fault the debugger sees, and
# what this emits is an ordinary exit with a NONZERO status. That is the same
# difference `raise` already has on this path (no unwinder, so an exception is
# `exit(1)`), and it is the reason the divergence is a reuse of that sequence
# rather than a new instruction: every word in it already has a `work_step_*`
# lemma in `lib/work.lean`, so a program containing one is still PROVABLE to
# the point the source stops, whereas an unmodelled `brk` word would fall
# through `formal/arm64_proof_gen.py`'s `_step_branch_index` as "not modelled"
# and be skipped. A trap instruction is the better lowering and is the one to
# build if the Lean model grows a step for it; until then this is the one that
# does not put a hole in the proofs.
#
# **Why only these two.** Every other member of `MLIR_EFFECT_OPS` is refused for
# a fact beyond the missing value: a `lit.ownership.mark_initialized` asserts
# something about a reference this path does not track, a `pop.store` has an
# ADDRESS whose pointee width nothing states, a `pop.fence` and a
# `pop.inline_asm` are ordering and clobber facts with no encoding agreed here,
# and a coroutine step is the shape this path lowers to a plain call. Emitting
# the divergence for any of those would be a different program wearing the same
# words. Four sites in the stdlib corpus reach this table, three of them in
# `std/sys` and `std/os`:
#
#     std/sys/debug.mojo:20        __mlir_op.`llvm.intr.debugtrap`()
#     std/sys/info.mojo:702        __mlir_op.`llvm.intr.trap`()
#     std/os/os.mojo:242           __mlir_op.`llvm.intr.trap`()     (_abort_base)
#     std/_plugin/selector.mojo:74 __mlir_op.`llvm.intr.trap`()
#
# and all four are standalone statements whose value nothing reads — which is
# the property `mlir_effects_all_lowered` requires and `MLIR_EFFECT_OPS`'s own
# membership rule ("the corpus uses it as a standalone statement at EVERY one of
# its sites") already measured.
MLIR_EFFECT_DIVERGENCE_OPS = frozenset((
    "llvm.intr.trap", "llvm.intr.debugtrap",
))

# ELEMENTWISE arithmetic: one operation applied to every element of its operand.
# For a scalar operand the result is the one 64-bit word this path has, and both
# architectures already emit that computation for the ordinary spelling. For a
# SIMD operand it is an N-lane vector, which is not a word. The name decides
# elementWISE-ness; the OPERAND decides which of the two, which is exactly the
# fact this path does not have.
MLIR_ELEMENTWISE_OPS = frozenset((
    "pop.add", "pop.sub", "pop.mul", "pop.div", "pop.floordiv", "pop.rem",
    "pop.neg", "pop.shl", "pop.shr", "pop.abs", "pop.max", "pop.min",
    "pop.floor", "pop.ceil", "pop.trunc", "pop.round", "pop.fma",
    "index.add", "index.sub", "index.mul", "index.divs", "index.shrs",
    "index.and",
))

# An operation whose result TYPE is written in its own bracket, as `_type=` or as
# a variant with no `_type=`. The missing fact is the same one for all of them and
# it is a TYPE rather than a value, which is why they are a class of their own and
# not a row each: `__mlir_type.…` and `__mlir_attr.`#pop.bin_op<add>`` inside the
# bracket are dialect objects, and this path's only value is a 64-bit word.
#
# MEMBERSHIP IS MEASURED: these are the operations that, at EVERY site in the
# stdlib corpus, carry such a bracket — `_type=`, `pred=`, `bin_op=`, `mask=`,
# `weak=`, `intrin=`, a `variant` discriminant, or a `kgen.struct` index. 31
# operations over 71 of the 259 sites. That is a property of the SOURCE SPELLING
# rather than of this path, which is what makes it safe to key on the name: the
# same spelling appears at every site, so a reader can find the bracket.
MLIR_TYPED_RESULT_OPS = frozenset((
    # casts and conversions: the result type IS the operation
    "pop.cast", "pop.cast_to_builtin", "pop.cast_from_builtin",
    "builtin.unrealized_conversion_cast", "pop.simd.splat",
    "llvm.mlir.undef", "kgen.rebind",
    # bitcasts: width and element type from the bracket
    "pop.pointer.bitcast", "pop.bitcast", "pop.union.bitcast",
    "pop.variant.bitcast", "lit.ref.from_pointer",
    "pop.pointer_to_index", "lit.ref.to_pointer", "lit.ref.pack.from_pointer_pack",
    # comparisons: a predicate, as `pop.cmp` is above but a second dialect's
    "index.cmp",
    # aggregates: an index, a mask or a discriminant, not a type alone
    "kgen.struct.extract", "kgen.struct.replace", "kgen.struct.gep",
    "kgen.variant.create", "kgen.variant.get", "kgen.variant.is",
    "kgen.variant.discr_gep", "lit.ref.pack.extract",
    "pop.array.get", "pop.array.repeat", "pop.array.replace",
    "pop.simd.shuffle",
    # atomics: the bin_op and the ordering are dialect attributes
    "pop.atomic.rmw", "pop.atomic.cmpxchg",
    # calls whose signature is a dialect type
    "pop.external_call", "pop.call_llvm_intrinsic", "pop.global_alloc",
    "pop.stack_allocation", "pop.aligned_alloc",
    "co.get_callback_ptr", "co.get_results", "co.resume",
    # bookkeeping with a type in its bracket
    "kgen.source_loc", "kgen.compile_offload",
))

# A VECTOR operation: its operand is `!kgen.simd<LENGTH, DTYPE>` and its result
# is N lanes, not a word. Decided by the `pop.simd.` prefix — a structural fact
# of the operation's NAME rather than of any particular site's types, which is
# what makes it safe to key on and what `MLIR_ELEMENTWISE_OPS` above deliberately
# does NOT do for `pop.add` (that one is scalar or vector depending on its
# operand, and the corpus has both).
#
# `reduce_and` / `reduce_or` are here rather than in the elementwise table
# because they are the opposite direction: they take N lanes and produce ONE
# scalar, so the operand is a vector and the result is a word — still not
# answerable here, because reading N lanes needs the vector this path does not
# hold, but a different fact from an elementwise widen.
MLIR_VECTOR_OPS_PREFIX = "pop.simd."

# An operation whose value could be a word but which needs a FACT this path does
# not have, named per operation because each needs a DIFFERENT missing thing and
# a refusal that says "no representation" when the real absence is a predicate
# sends the reader looking for the wrong one:
#
#   * `pop.cmp` — needs the bracketed `#kgen.cmp_pred<…>` PREDICATE, which is
#     itself a dialect attribute, and six distinct values appear in the corpus.
#   * `pop.select` — its first argument is a BOOL (`condition.__mlir_bool__()`),
#     and this path has no BOOL kind distinct from INT, so a select answered
#     kind-blind would test a `char *` for non-zero. Same missing piece
#     `MLIR_BOOL_METHODS` names for the method itself.
#   * `pop.load` / the pointer casts — a load's width is its POINTEE's, and this
#     path refuses an undeclared pointee elsewhere (`std/utils/_serialize.mojo`'s
#     next terminal is exactly that refusal).
MLIR_UNGUARDED_OPS = {
    "pop.cmp": ("it needs the `#kgen.cmp_pred<…>` PREDICATE in its bracket to "
                "say which comparison it is, and that predicate is itself a "
                "dialect attribute rather than a value"),
    "pop.select": ("its first argument is a BOOL (`condition.__mlir_bool__()`), "
                   "and this path lowers that only when the receiver's "
                   "DECLARED type says `Bool` — an unannotated word is an "
                   "integer here, so a select answered kind-blind would test a "
                   "`char *` for non-zero and answer 1. The missing thing is "
                   "therefore the declaration and not a kind: "
                   "`formal.types.BOOL_TYPE_NAMES` names the annotations that "
                   "carry it and `annotation_is_bool` is the one reader of "
                   "them. `std/utils/_select.mojo` declares `condition: Bool` "
                   "and IS lowered, so this row is reached only by a program "
                   "that does not say what its word holds"),
    "pop.load": ("its width is its POINTEE's, and nothing here states a pointee "
                 "type for this receiver"),
    "pop.offset": ("it is POINTER arithmetic, so its scale is the pointee's "
                   "width and nothing here states one"),
    "pop.array.gep": ("it is a GEP into an aggregate, so the element width and "
                      "the index scale are the aggregate's and nothing here "
                      "states them"),
    "pop.variant.discr_gep": ("it is a GEP onto a VARIANT's discriminant, so "
                              "the offset and the width are the variant's "
                              "layout and nothing here states either"),
    "pop.string.size": ("its receiver is a dialect STRING object rather than a "
                        "value this path holds, and a string's length is a "
                        "property of the buffer that object points at, not of "
                        "the word the reference is"),
    "pop.string.address": ("its result is the ADDRESS of a dialect string "
                           "object's buffer, which is a fact about a container "
                           "this path does not build rather than about a word"),
    "kgen.struct.load_indirect": ("it reads a struct out of a dialect VALUE PACK, "
                                  "whose layout is a dialect type rather than a "
                                  "word"),
    "lit.ref.struct.ger": ("it reads a struct field out of a dialect "
                           "REFERENCE, which is a compiler-internal object this "
                           "path does not hold"),
    "pop.dtype.to_ui8": ("it reads a dtype's encoding, which is a dialect dtype "
                         "object rather than the value this path represents"),
    "pop.dtype.from_ui8": ("it reads a dtype's encoding, which is a dialect "
                           "dtype object rather than the value this path "
                           "represents"),
    "pop.noalias_pointer_cast": ("its result's provenance is a compiler-level "
                                 "`noalias` fact about a pointer's users, which "
                                 "no word records"),
    "pop.global_constant": ("its value is the linker-resolved content of a "
                            "symbol, and this path compiles each module to its "
                            "own image rather than linking one against another"),
    # The version triple: a dialect attribute with no representation, read at
    # build time by the compiler that HAS MLIR and by nothing else.
    "lit.mojo.version.major": ("the Mojo version is a compiler-build attribute, "
                               "not a value any image holds"),
    "lit.mojo.version.minor": ("the Mojo version is a compiler-build attribute, "
                               "not a value any image holds"),
    "lit.mojo.version.patch": ("the Mojo version is a compiler-build attribute, "
                               "not a value any image holds"),
}



# ── The OPERAND's DECLARED type, which is the fact every arithmetic arm needs ──
#
# The operation-vs-operand-type correction measured the thing this section
# exists for: counted by OPERATION
# NAME, the corpus's arithmetic sites look scalar (38 sites over 27 operations,
# the names read `add`/`sub`/`mul`/`cmp`), and a table keyed on the name that
# emitted `a + b` for `pop.add` would be RIGHT for 9 of them and WRONG for 26.
# The 26 are `std/simd.mojo`, whose own source documents the operation it
# applies to — "a new vector whose element at position `i` is computed as
# `self[i] + rhs[i]`" — over a field declared
# `var _mlir_value: Self._mlir_type`, where `_mlir_type` is a `comptime`
# built from `__mlir_type[`!kgen.simd<`, …]`. So the name settles
# elementWISE-ness and the OPERAND settles word-or-N-lanes, and the operand is
# only ever stated in the SOURCE: as a parameter annotation, a local
# annotation, or a struct field's declaration.
#
# Everything below reads a DECLARATION and nothing else. That is the discipline
# `_declared_bool_locals` established for `pop.select` (whose guard is the same
# kind of fact — "does the source say this word holds 0 or 1") and it is
# deliberate for the same reason: a value's provenance is not a declaration, so
# a comparison, a cast or a call result establishes nothing here and is left
# refused. A reader that could answer from a KIND instead would be able to
# answer about a `char *`, which is the wrong answer this whole backend exists
# to prevent.
#
# LEAF-MOST, like every other table in this section, so both architectures and
# the build pass that lowers the operation cannot disagree about what a dialect
# operand denotes.

# The dialect types this path holds in ONE 64-bit word, by their declared
# spelling after the `__mlir_type.` prefix and the backticks are removed.
#
# **One name, and that is a measurement rather than an undercount.**
# `__mlir_type.index` is pointer-sized and signed, which is every property the
# arithmetic below needs (a truncating division, an arithmetic right shift, a
# signed comparison — and the truncating division is `/`, not `//`, since the
# floor correction landed; see `MLIR_WORD_ARITH_OPS`'s own block, which is where
# that fact is measured). `!kgen.scalar<uiN>` is a single scalar too and is
# deliberately NOT here: an N-bit unsigned integer held in a word wraps at 2^N,
# so `a + b` over two `ui8` is not the 64-bit add this path emits — answering
# it would be a wrong answer, and the doc's own count of the 9 word-typed
# sites calls `!kgen.scalar<ui8>` word-typed, which this corrects rather than
# repeats.
MLIR_WORD_TYPE_NAMES = frozenset(("index",))

# A VECTOR type: N lanes, never a word. Decided on the type's own spelling, so
# it is structural rather than per-site — the same property of the NAME that
# makes `MLIR_VECTOR_OPS_PREFIX` safe to key on and `MLIR_ELEMENTWISE_OPS`
# unsafe to.
MLIR_VECTOR_TYPE_PREFIXES = ("!kgen.simd<", "!kgen.masked<")

# The names a method's receiver travels under, including the source-level
# alias `Self`. Recognised so that `<receiver>.<field>` can be read as a field
# of this function's own struct without resolving which struct that is — the
# field table below is keyed on the field and refuses a name two structs
# declare differently, so an owner-free read is not a guess.
MLIR_SELF_TYPE_NAMES = frozenset(("self", "this", "Self"))

# The elementwise operations this path REWRITES when the operand's declared type
# is one word, and the ordinary operator each denotes. Rewriting to the
# ordinary spelling rather than adding an instruction selection is the whole of
# the design, and it is the reason the design note's "each arm must select
# instructions from the decisions the two backends already SHARE" is satisfied
# by construction: `+`,
# `-`, `*`, `/`, `%`, `&`, `>>` already go through `common_type`, `cmp_signed`
# and `shift_signedness` in both emitters, so an arm here that would re-decide
# any of them would be a second copy of an answer that exists.
#
# ## THE DIVISION ROWS, and they are the ones that needed MEASURING rather than
# ## reading — because this path's `//` and `%` are NOT Python's and HAVE
# ## CHANGED.
#
# The table was first written against a measurement that has since been
# INVERTED, and the two entries keyed on it were silent wrong answers for as
# long as that took:
#
#     f(-7, 2)                            this path NOW   CPython
#       a // b                                -4  floor      -4
#       a %  b                                 1  divisor    1
#       a /  b                                -3  TRUNCATES  -3.5   (§6 Phase 7)
#
# `model.division_floors` (below) is the one decision both emitters ask, and
# `lib/ProofLib.lean`'s `fdiv64`/`frem64` are what the source model names; both
# landed with the floor correction. Before them the same program gave `-3`, `-1`
# and `-3`, so `//` truncated and `%` carried the DIVIDEND's sign — which is
# exactly `index.divs` and exactly `pop.rem`, and the table said so. Both of
# those rows were therefore RIGHT when written and wrong the moment the path
# started flooring, which is the shape of hazard this section exists to prevent
# and the reason the rows are re-derived from `division_floors` rather than
# from a comment:
#
#   * **`index.divs` → `/`.** `index.divs` is a TRUNCATING signed division, and
#     this path's `/` on a signed operand is exactly that —
#     `division_floors("/", signed)` is False and its own docstring says why
#     ("there is no float on this path … so `/` is the int-only truncation").
#     It was `//`, which was the same function while `//` truncated.
#   * **`pop.rem` → `"srem"`, the shape below.** `pop.rem` is LLVM's `srem`, a
#     remainder carrying the DIVIDEND's sign; this path's `%` carries the
#     DIVISOR's, so `%` is wrong for it whenever the signs differ. There is no
#     one-operator spelling, so the table carries the IDENTITY and the rewrite
#     builds it: `a - (a / b) * b`, which is `srem` exactly because `/` truncates.
#
# **BOTH rows therefore depend on `/` meaning INTEGER truncation**, which is a
# documented Phase-7 stand-in and not a promise: when real division lands, these
# two entries have to be re-derived and this comment is what a reader consults
# first. The dependency is CHECKED rather than trusted —
# `test_formal_mlir_precedence.py` pins `a / b` for a negative operand on BOTH
# architectures, so the day `/` stops truncating that row goes red in the same
# commit as the change rather than leaving a wrong answer behind a true
# comment. That is the whole difference between this block and a bare list.
#
# `pop.floordiv` is NOT in this table, and that is now a deliberate
# non-widening rather than a correctness gap: this path's `//` IS floor, so
# `pop.floordiv` → `//` would be exact, and the reason to leave it out is that
# no site in the corpus reaches it (`std/builtin/simd_length.mojo`'s six
# `index.*` operations are add/sub/mul/and/divs/shrs). The doc's own §
# Correction argues against a widening on the strength of a caller that does not
# exist. `pop.div` is absent for the other half of the same question — the name
# does not say which division it is, and a table that picked one would be the
# name-keyed table § Correction is about.
#
# The three shapes, and the third is why the third exists: `("binary", op)` is
# one operator between two operands, `("unary", op)` is one operand, and
# `("srem", None)` is the one operation this path has no single operator for —
# `formal/build.py::_dialect_arith_replacement` is the only reader of all three,
# so the shape and the rewrite cannot come to disagree about which is which.
MLIR_WORD_ARITH_OPS = {
    "index.add": ("binary", "+"),
    "index.sub": ("binary", "-"),
    "index.mul": ("binary", "*"),
    "index.divs": ("binary", "/"),
    "index.and": ("binary", "&"),
    "index.shrs": ("binary", ">>"),
    "pop.add": ("binary", "+"),
    "pop.sub": ("binary", "-"),
    "pop.mul": ("binary", "*"),
    "pop.rem": ("srem", None),
    "pop.neg": ("unary", "-"),
}

# The COMPARISON operations: the operation name says nothing and the whole of
# the answer is in the bracket. Kept apart from `MLIR_WORD_ARITH_OPS` because
# the predicate has to be read first, and a table that read the name and
# ignored the bracket would answer `eq` and `ne` the same way — a wrong answer
# rather than a refusal, which is the sentence `MLIR_UNGUARDED_OPS["pop.cmp"]`
# and `MLIR_TYPED_RESULT_OPS["index.cmp"]` already refuse.
MLIR_CMP_OPS = frozenset(("pop.cmp", "index.cmp"))

# A bracketed dialect predicate, and the ordinary comparison it denotes.
#
# **The set is closed on purpose and it is SIGNED.** `slt`/`sle`/`sgt`/`sge` say
# what they are; `lt`/`le`/`gt`/`ge` are the unsigned spelling of the same four
# in the corpus, and they are answered because an `index` operand is a SIGNED
# 64-bit integer whatever the predicate is called — the operand's declared type,
# not the predicate, is what fixes the comparison. `ult`/`ule`/`ugt`/`uge` are
# deliberately absent: this path's `<` is signed (measured, same program as the
# divisors above), there is no unsigned spelling to rewrite to, and answering an
# unsigned predicate with a signed comparison is the wrong answer in the exact
# shape this section is arranged to prevent. One `ult` site is in the corpus
# (`std/_plugin/selector.mojo`) and it stays refused.
MLIR_CMP_PRED_OPS = {
    "eq": "==", "ne": "!=",
    "lt": "<", "le": "<=", "gt": ">", "ge": ">=",
    "slt": "<", "sle": "<=", "sgt": ">", "sge": ">=",
}


def mlir_type_kind(ann):
    """`'word'`, `'vector'`, or None — what a DECLARED dialect type denotes.

    Three answers rather than two, and None is the common one: a spelling this
    path cannot classify claims nothing, which is the direction a refusal has
    to fail in. A `comptime` ALIAS (`Self._mlir_type`, which is how 26 of the
    corpus's arithmetic sites spell their operand) is one of the Nones, and it
    is the case the whole design turns on — the alias resolves to a vector, so
    answering it from the spelling `Self._mlir_type` would be a scalar add of
    two vector-typed words.

    The spelling is normalised by removing the `__mlir_type.` prefix and a pair
    of surrounding backticks, because the corpus writes the same type three
    ways: `__mlir_type.index`, ``__mlir_type.`!kgen.simd<4, ui32>` `` and
    `!kgen.simd<4, ui32>`.
    """
    if not isinstance(ann, str):
        return None
    text = ann.strip()
    if text.startswith(MLIR_DIALECT_TYPE_PREFIX):
        text = text[len(MLIR_DIALECT_TYPE_PREFIX):]
    if len(text) >= 2 and text[0] == "`" and text[-1] == "`":
        text = text[1:-1]
    if text in MLIR_WORD_TYPE_NAMES:
        return "word"
    for prefix in MLIR_VECTOR_TYPE_PREFIXES:
        if text.startswith(prefix):
            return "vector"
    return None


def mlir_operand_declared_type(expr, names, fields, struct_names=()):
    """The DECLARED type spelling of a dialect operation's OPERAND, or None.

    `names` is `{name: annotation or None}` for the names ONE function binds —
    its parameters, its annotated locals and its receiver — `fields` is
    `{field: annotation}` over the structs of the unit, keeping only a field
    name exactly one struct declares, and `struct_names` is the set of struct
    names the unit DECLARES. `None` is the answer for every shape nothing in
    the source states: a call result, a subscript, a comparison, an arithmetic
    expression, a field read through a base nothing types, and a field two
    structs declare differently.

    **A field read is only read off a base this can TYPE**, and that is the
    whole of the member half's safety argument. `self._mlir_value` is the shape
    six of the corpus's nine word-typed sites are written in, and it is read
    from `MLIR_SELF_TYPE_NAMES` — a receiver is `self`, and `self` is a
    receiver because of where it is spelled, not because of an annotation.
    Beyond that the base must be a name this function declares as a STRUCT OF
    THIS UNIT (`a: Vec` reading `a.v`). The rule is not tidiness: measured on
    this tree, `SIMDLength___init__(out self, value: Int)` writing
    `__mlir_op.`pop.cast_to_builtin`[…](value._mlir_value)` had `_mlir_value`
    read off `SIMDLength`'s own field table and claimed `__mlir_type.index` for
    an operand that is an `Int`'s dialect value — a fact about the field NAME
    rather than about the field the source wrote.
    """
    if isinstance(expr, F.IdentExpr):
        return names.get(expr.name)
    if isinstance(expr, F.MemberExpr) and isinstance(expr.obj, F.IdentExpr):
        base = expr.obj.name
        if base in MLIR_SELF_TYPE_NAMES:
            return fields.get(expr.member)
        ann = names.get(base)
        if not isinstance(ann, str) or not struct_names:
            return None
        owner = annotation_base_name(ann) or ann.split(".")[0]
        if owner not in struct_names:
            return None
        return fields.get(expr.member)
    return None


def mlir_cmp_predicate_op(bracket):
    """The ordinary comparison a bracketed dialect PREDICATE denotes, or None.

    `bracket` is the `F.SubscriptExpr` a `pop.cmp`/`index.cmp` is spelled with,
    and the answer comes from a CLOSED set (`MLIR_CMP_PRED_OPS`) read out of
    the `pred=` attribute's own spelling — `#index.cmp_predicate<eq>` and
    `#kgen.cmp_pred<ne>` are the two dialects' two spellings of the same
    vocabulary, and both appear in the corpus.

    None for everything else, and each of the None answers is a different
    refusal: an attribute this path does not recognise, a bracket with no
    `pred=` at all, a `pred=` whose value is not a dialect attribute (a
    comptime name or a call is a fact this build cannot read), and a predicate
    outside the closed set — which includes every UNSIGNED one, because the
    ordinary comparison is signed and there is no unsigned spelling to rewrite
    to.
    """
    if not isinstance(bracket, F.SubscriptExpr):
        return None
    value = None
    for attr in getattr(bracket, "attrs", None) or []:
        if isinstance(attr, (tuple, list)) and len(attr) == 2 and attr[0] == "pred":
            if value is not None:
                return None               # two `pred=`: no single answer
            value = attr[1]
    if not isinstance(value, F.MemberExpr):
        return None
    if not isinstance(value.obj, F.IdentExpr) \
            or value.obj.name != MLIR_ATTR_ROOT:
        return None
    member = value.member
    if not (isinstance(member, str) and member.startswith("`")
            and member.endswith("`") and len(member) >= 2):
        return None
    spelling = member[1:-1]
    start = spelling.find("<")
    if start < 0 or not spelling.endswith(">"):
        return None
    return MLIR_CMP_PRED_OPS.get(spelling[start + 1:-1])


def mlir_operand_clause(operand) -> str:
    """One sentence about an OPERAND whose DECLARED type this build read.

    The sentence is what keeps `mlir_dialect_op_refusal` from becoming false at
    a site the operand type IS established for, which is the disease that
    document is about and the one this function's existence creates: "this
    path has no lowering table that establishes the operand type" is untrue of
    `pop.add` over a declared `__mlir_type.index`, and untrue of `pop.add` over
    a declared `!kgen.simd<4, ui32>` in a different direction. Two answers and a
    None, because a sentence about the OPERAND that also claimed something
    about the OPERATION would be false of every operation this path declines for
    a reason other than its operands — which is most of them: `pop.cmp` over a
    word is missing its PREDICATE, not its operand type, and the clause says
    nothing about the operation on purpose.

    The word clause therefore stops where the fact stops: it says the result is
    something this path's only value can hold, and the OPERATION's own missing
    piece is the refusal text's own business.
    """
    kind = mlir_type_kind(operand)
    if kind == "word":
        return (f" Its operand is declared {operand!r}, which is ONE 64-bit "
                f"word here — a signed, pointer-sized integer — so whatever "
                f"this operation denotes is something this path's only value "
                f"can hold.")
    if kind == "vector":
        return (f" Its operand is declared {operand!r}, which is an N-LANE "
                f"VECTOR and not a word at all, so the element width and the "
                f"lane count are facts this path has no source for.")
    return ""


# The bracket attribute that names an operation's RESULT TYPE.  ONE name, and it
# is the only one in the corpus: `_type=`, on `pop.cast`, `pop.cast_to_builtin`,
# `pop.cast_from_builtin`, `builtin.unrealized_conversion_cast`, `pop.simd.splat`
# and the rest of `MLIR_TYPED_RESULT_OPS`.  A bracket carries OTHER things — a
# `pred=`, a `bin_op=`, a `mask=`, an `ordering=`, a variant discriminant — and
# none of them is a type, so this is keyed on the name rather than on "any
# attribute in the bracket".  A name that is not in the corpus is not in this
# tuple: reading an unrecognised attribute as a result type would answer a
# question nobody asked, which is the name-keyed mistake
# `MLIR_WORD_ARITH_OPS`'s own comment is about.
MLIR_RESULT_TYPE_ATTRS = ("_type",)


# What each word-to-word CAST would become if this path answered it, keyed on
# the whole dialect name.  The shape of the answer is the claim, and it is
# checked by a row that BUILDS AND RUNS each one on both architectures rather
# than by reading this table — a cast whose rewrite is subtly not the identity
# is a wrong answer wearing a lowering, which is the outcome `MLIR_WORD_ARITH_OPS`
# § Correction is entirely about and the reason that table was re-derived when
# the floor correction landed.
#
# **`pop.cast_to_builtin[_type=index](x)` is the IDENTITY and is the one the
# corpus reaches**, read out of the stdlib's own spelling rather than inferred
# from the name: `std/builtin/simd_length.mojo:76` is
# `pop.cast_to_builtin[_type=__mlir_type.index](value._mlir_value)` on an
# `Int`'s dialect value, and an `index` is pointer-sized and signed, so the
# cast converts one word to the same word. It is NOT in `MLIR_WORD_ARITH_OPS`
# because that table rewrites OPERATIONS over two operands into a binary
# expression and this one is a unary identity over one — a different shape, in a
# different pass (`formal/build.py::_lower_dialect_casts`, beside
# `_lower_dialect_arith` and for the same reason: a construct both backends would
# otherwise have to be taught separately).
#
# The other two casts are here as NAMES THIS PATH DECLINES, each with the reason
# it is a refusal and not a rewrite, and neither may be widened by reading the
# table: `pop.cast_from_builtin` converts a builtin value INTO a dialect one,
# which for `index` is the identity in the other direction and for every other
# type is the very conversion this path has no representation for; and a
# `builtin.unrealized_conversion_cast` names a conversion the SOURCE does not
# spell out at all, which is the §Correction argument in its purest form — a name
# that does not say what it computes.
MLIR_WORD_CAST_OPS = {
    "pop.cast_to_builtin": (
        " It is the IDENTITY over a word: `pop.cast_to_builtin[_type="
        "__mlir_type.index](x)` converts one `index` to the same `index`, so the "
        "rewrite is the operand itself with no instruction selection at all. "
        "`formal/build.py::_lower_dialect_casts` does it in the shared pipeline, "
        "so both architectures get it by construction rather than by agreeing."),
    "pop.cast_from_builtin": (
        " It converts a builtin value INTO a dialect one, which is the "
        "identity in the other direction for `__mlir_type.index` and a "
        "conversion this path has no representation for at every other type — so "
        "the operation, not the representation, is what is missing here."),
    "builtin.unrealized_conversion_cast": (
        " It names a conversion the source does not spell out at all, so there "
        "is nothing in the unit that says what it computes: which is the §"
        "Correction argument about a table keyed on the operation's NAME, and "
        "the reason no rewrite is offered for it."),
}


# **THE ONE ROW OF `MLIR_WORD_CAST_OPS` THIS PATH ANSWERS**, and it is one name
# rather than three because the other two are documented DECLINES and a decline
# that a rewriting pass matches is a wrong answer: the table is the refusal's
# vocabulary — "here is what this operation would become, and here is why we do
# not" — while the rewrite is the set of operations whose second half has
# happened. Naming them in one table and asking membership of it would rewrite
# `builtin.unrealized_conversion_cast[_type=__mlir_type.index](x)` to `x`,
# which is a conversion this path has no source for, and it did: measured on
# this tree, the first version of `_lower_dialect_casts` gated on
# `MLIR_WORD_CAST_OPS` and built that program on both architectures, where the
# whole point of the row is that it must not.
#
# So the answerable set is a name of its own and the table's docstring says why
# it is separate — the same agree-or-refuse discipline every other
# "which of these does this path handle" question in this file keeps, and the
# same one `MLIR_WORD_ARITH_OPS` keeps for a different reason (that table is
# keyed on the OPERATION because the operand type settles word-or-vector, and
# this one is keyed on the operation because the OPERATION settles whether there
# is a conversion at all).
MLIR_WORD_CAST_LOWERED = ("pop.cast_to_builtin",)


def mlir_dialect_cast_advice(op: str, bracket, operand) -> str:
    """What this cast would become, for a site whose operand type IS declared.

    ONE reader for the refusal text and the lowering table, and the reason is
    the same one every other shared reader in this file carries: two copies of
    "which casts this path answers" are two places for them to disagree, and the
    disagreement would be a refusal telling a reader that an operation is
    declined while the pass rewrites it — or the reverse, which is worse, because
    it is a wrong answer.

    A name in `MLIR_WORD_CAST_OPS` that this site does NOT match (a bracket
    carrying something other than a `_type=`, or a result type that is not a
    word) gets the generic half and not the row, because the row is a claim about
    a specific rewriting and this site is not that shape. Only the two gate
    conditions `_lower_dialect_casts` itself applies are asked here, so the
    message and the rewrite cannot disagree about which sites are in scope.
    """
    row = MLIR_WORD_CAST_OPS.get(op)
    if row is None:
        return (" No table entry names it, and an operation this path does not "
                "recognise is declined by name rather than guessed at.")
    if not isinstance(bracket, F.SubscriptExpr) \
            or mlir_type_kind(mlir_bracket_result_type(bracket)) != "word":
        return (" This site is not the shape its row describes — the rewrite "
                "needs a bracket naming a word result type — so it is declined "
                "rather than rewritten.")
    return row


def mlir_bracket_result_type(bracket):
    """The SPELLING of the result type in a dialect bracket, or None.

    `bracket` is the `F.SubscriptExpr` an operation is written with, and the
    answer is the `_type=` attribute's own value rendered as the source spells
    it — `__mlir_type.index`, or ``__mlir_type.`!kgen.simd<4, ui32>` `` — because
    a message that quotes the source is the only one a reader can check against
    it. `mlir_type_kind` is what turns that spelling into `word`/`vector`/None.

    None for a bracket with no `_type=`, for one with TWO of them (no single
    answer), and for a value this build cannot render: a `comptime` name, a
    template built from several fragments, a call. Each of those is a different
    refusal and none of them may be answered as "no type is written here",
    because a bracket that names a type by a name this build cannot resolve has
    named one.
    """
    if not isinstance(bracket, F.SubscriptExpr):
        return None
    value = None
    for attr in getattr(bracket, "attrs", None) or []:
        if isinstance(attr, (tuple, list)) and len(attr) == 2 \
                and attr[0] in MLIR_RESULT_TYPE_ATTRS:
            if value is not None:
                return None                      # two `_type=`: no single answer
            value = attr[1]
    return _mlir_type_spelling(value)


def _mlir_type_spelling(node):
    """`__mlir_type.index` as the source spells it, or None.

    The corpus writes the same type three ways — `__mlir_type.index`,
    ``__mlir_type.`!kgen.simd<4, ui32>` `` and bare `!kgen.simd<4, ui32>` — and
    the first two arrive as a `MemberExpr` whose object is the bare `__mlir_type`
    root and whose member is the backtick-quoted name, which is the same shape
    `mlir_dialect_op_name` reads for an operation. The third is a bare
    `IdentExpr`. Both are rendered here so the message can quote the source's own
    spelling rather than a normalised one.

    None for anything else, and a `MemberExpr` over some OTHER root is NOT a type
    — `__mlir_attr.`#kgen.cmp_pred<eq>`` is an attribute, and answering it with
    a type would be the false answer this whole arrangement exists to prevent.
    """
    if isinstance(node, F.MemberExpr) and isinstance(node.obj, F.IdentExpr) \
            and node.obj.name == MLIR_DIALECT_TYPE_ROOT:
        member = node.member
        if not isinstance(member, str) or not member:
            return None
        if member[0] == "`" and member[-1] == "`" and len(member) >= 2:
            # A name the dialect spells with characters Python would read as
            # syntax comes back quoted (`!kgen.simd<4, ui32>`), and the quotes
            # are part of the source's spelling, so they stay.
            return f"{MLIR_DIALECT_TYPE_ROOT}.{member}"
        # `__mlir_type.index` — the corpus's own spelling for the one word type,
        # with no quotes, because `index` needs none.
        if "`" in member or " " in member:
            return None
        return f"{MLIR_DIALECT_TYPE_ROOT}.{member}"
    if isinstance(node, F.IdentExpr):
        return node.name
    return None


def mlir_result_clause(bracket) -> str:
    """One sentence about a RESULT TYPE this build read out of the bracket.

    **The same treatment `mlir_operand_clause` gives the operand, and for the
    same reason.** The typed-result refusal says "that bracket holds a DIALECT
    object (`__mlir_type.…`) rather than a value … so the result's width and
    element type are a fact it has no source for" — and that is FALSE at every
    site whose `_type=` is a type this path classifies, which is the disease the
    elementwise branch was fixed for in 2026-10-04 and the same disease one
    branch over. `std/builtin/simd_length.mojo`'s
    `pop.cast_to_builtin[_type=__mlir_type.index](value._mlir_value)` is the
    case: `index` is in `MLIR_WORD_TYPE_NAMES`, so the result IS one 64-bit word
    here, and what is missing is the OPERAND's declared type — `value._mlir_value`
    is a field of `Int`, a builtin struct this unit does not declare.

    Two answers and a None, like the operand's:
      * `word` — the result is this path's only value, so the missing thing is
        named as the operand rather than as the result;
      * `vector` — the lane count and element width are the missing facts, which
        is a different thing from the operand's type and says so;
      * None, or a bracket with no `_type=` — nothing, so the class's own
        sentence stands unchanged.
    """
    spelling = mlir_bracket_result_type(bracket)
    kind = mlir_type_kind(spelling)
    if kind == "word":
        return (f" Its bracket's result type is {spelling!r}, which this path "
                f"holds in ONE 64-bit word — a signed, pointer-sized integer — "
                f"so the RESULT is not what is missing here.")
    if kind == "vector":
        return (f" Its bracket's result type is {spelling!r}, which is an "
                f"N-LANE VECTOR and not a word at all, so the lane count and "
                f"the element width are the facts this path has no source "
                f"for.")
    return ""


def mlir_dialect_op_name(node):
    """The dialect operation `node` spells, or None if it spells none.

    `__mlir_op.`pop.add`` is a `MemberExpr` whose `member` is the
    backtick-quoted operation name and whose object is the bare `__mlir_op`; the
    bracketed form (`__mlir_op.`pop.cmp`[pred=…](…)`) wraps that in a
    `SubscriptExpr`. Keys on the ROOT being `__mlir_op` rather than on any
    backtick in sight, so a template fragment elsewhere in the body is not
    mistaken for an operation — the same discipline `_bracket_callee_roots`
    records by node IDENTITY for the same reason."""
    if isinstance(node, F.SubscriptExpr):
        node = node.obj
    if not isinstance(node, F.MemberExpr):
        return None
    if not isinstance(node.obj, F.IdentExpr) \
            or node.obj.name != "__mlir_op":
        return None
    name = node.member
    if not (isinstance(name, str) and len(name) >= 2
            and name[0] == "`" and name[-1] == "`"):
        return None
    return name[1:-1]


def mlir_effect_diverge_call(expr):
    """The divergence `expr` denotes, or None if it is not a lowerable one.

    `expr` is lowered only when it is a dialect-operation CALL with NO
    arguments whose operation is in `MLIR_EFFECT_DIVERGENCE_OPS`. The argument
    count is part of the predicate rather than an assumption about the dialect:
    a trap takes none in every spelling in the corpus, and a site that passed
    one would be asking this path to compute something before it stops, which
    is a different construct that deserves its own refusal.

    This is the ONE reader of that table, and both backends' statement emitters
    ask it through here rather than reading the set each — the failure mode this
    module exists to prevent is two backends disagreeing about what a dialect
    operation denotes, and a per-emitter copy of the set is how that happens.
    """
    if not isinstance(expr, F.CallExpr) or expr.args:
        return None
    op = mlir_dialect_op_name(expr.func)
    if op is None or op not in MLIR_EFFECT_DIVERGENCE_OPS:
        return None
    return op


def mlir_effects_all_lowered(body) -> bool:
    """True when `body`'s ONLY dialect constructs are lowered effects.

    The question `formal/build.py`'s name-placement pass asks before it refuses
    a function for naming a dialect root: is there anything here this path
    cannot lower? A trap used as a statement has nothing to represent and
    nothing that reads a result, so it is not that — and a function may hold
    several sites, so the answer is over the WHOLE body and not over the site
    the walk happened to reach.

    Every dialect root in `body` must therefore be accounted for twice: by
    identity, so that no `__mlir_*` name is left over by a walk that counted
    only the calls it recognised, and by POSITION, so that each recognised call
    is the whole value of an `F.ExprStmt` rather than something an assignment
    or a `return` reads. Both halves are needed and neither subsumes the other:
    the identity half stops a second construct from riding along unseen, and
    the position half is what "the value is discarded" actually means — a
    `return __mlir_op.`llvm.intr.trap`()` is a value position whatever the
    arguments are.

    False when there is no dialect construct at all, so a caller cannot read
    "nothing to refuse" as "everything here lowers".
    """
    roots = set()
    for node in iter_nodes(body):
        if isinstance(node, F.IdentExpr) \
                and node.name.startswith(MLIR_DIALECT_PREFIX):
            roots.add(id(node))
    if not roots:
        return False
    stmt_values = {id(s.value) for s in iter_nodes(body)
                   if isinstance(s, F.ExprStmt)}
    calls = [c for c in iter_nodes(body) if mlir_effect_diverge_call(c)]
    if not calls:
        return False
    lowered = set()
    for call in calls:
        if id(call) not in stmt_values:
            return False
        root = call.func
        while isinstance(root, (F.MemberExpr, F.SubscriptExpr)):
            root = root.obj
        lowered.add(id(root))
    return lowered == roots


def mlir_dialect_op_refusal(op: str, operand: str = None,
                            bracket=None) -> str:
    """Why this path refuses the dialect OPERATION `op`, by what it denotes.

    Four sentences for four different facts, because ONE sentence over all of
    them was false of a measurable subset — see `MLIR_ELEMENTWISE_OPS` for the
    census, and note that the split is by DENOTATION and by the op NAME, because
    the name is all this table has. Nothing here claims an operation "denotes a
    word": whether an elementwise operation's result is a word is a fact about
    its OPERANDS, and 26 of the 38 sites measured have a vector operand, so
    asserting it would be the same over-claim in a new place.

    `bracket` is the operation's own `F.SubscriptExpr` when it is written with
    one, and it is read only by the typed-result branch — the class whose
    missing fact IS the bracket. It is here for the same reason `operand` is
    (2026-10-04, and again a day later for the other half): the class's sentence
    said the result's width and element type are "a fact this path has no
    source for", which is FALSE of every `_type=` this path classifies — and
    `simd_length.mojo`'s `pop.cast_to_builtin[_type=__mlir_type.index]` is one.
    `mlir_result_clause` reports what the bracket says and, where it says
    nothing this build can read, the class's own sentence stands unchanged.

    **Except where `operand` says otherwise**, which is the one thing that
    changed when the operand's DECLARED type became readable
    (`mlir_operand_declared_type`). With the type in hand the refusal can no
    longer say "this path has no lowering table that establishes the operand
    type" at a site where the type IS established — so `mlir_operand_clause`
    appends what the declaration actually says, and the sentence that used to
    cover the class unconditionally now covers only the sites nothing in the
    source states a type for. That is the same disease one step further in: a
    diagnostic that cannot see a fact it now has. `operand` is the annotation
    SPELLING (or None), never a kind, because a message that quotes the
    reader's own declaration is the only one that can be checked against it.

    The order is effect, unguarded, typed-result, elementwise, then an honest
    fallback for an operation nobody classified. Every branch is ARCH-FREE and
    the tables are in this module, so the two backends cannot disagree about
    what a dialect operation denotes — the failure mode this file's design
    exists to prevent, and the one a per-emitter copy of these tables would
    walk into."""
    if op in MLIR_EFFECT_OPS:
        return (
            f"`{op}` is a dialect OPERATION and denotes NO VALUE: it is an "
            f"EFFECT — something that happens rather than something whose "
            f"result a register could hold — so there is no representation for "
            f"it in a 64-bit word because there is no value to represent. This "
            f"path has no MLIR, so it lowers a Mojo program to a Mach-O image "
            f"whose only value is a 64-bit word. Refused rather than read out of "
            f"a register, which is what produced 10 on arm64 and 0 on x86-64 for "
            f"one source"
        )
    if op in MLIR_UNGUARDED_OPS:
        return (
            f"`{op}` is a dialect OPERATION whose value could be a word on this "
            f"path, but it cannot be GUARDED here: {MLIR_UNGUARDED_OPS[op]}. "
            f"A deliberate deferral, not an impossibility: the operation is "
            f"nameable and its operands are values, so what is missing is the "
            f"fact its result depends on — not a representation of the result."
            + mlir_operand_clause(operand)
        )
    if op in MLIR_TYPED_RESULT_OPS:
        # Read ONCE and decide from it: the class's sentence, the clause that
        # reports what the bracket says, what is missing and the advice that
        # follows are four statements about the same fact, and asking
        # `mlir_type_kind` four times is four places for them to disagree.
        rkind = mlir_type_kind(mlir_bracket_result_type(bracket))
        okind = mlir_type_kind(operand)
        if rkind == "word" and okind is None:
            tail = (" What is therefore missing is the OPERAND's DECLARED type, "
                    "and nothing in this unit states one: a DECLARATION is "
                    "what this path reads, and a field read off a struct the "
                    "unit does not declare — a builtin such as `Int`, which has "
                    "no field table here — states nothing about its type. A "
                    "deliberate deferral, not an impossibility: the operation "
                    "is nameable and its result is one word, so what is "
                    "missing is a fact about the operand rather than a "
                    "representation of the result.")
        elif rkind == "word":
            # **The operand's type IS established here, and the sentence above
            # would be FALSE of it.** `mlir_operand_clause`, appended right
            # after this one, then says "Its operand is declared
            # '__mlir_type.index'", so the two halves of one message
            # contradicted each other:
            #
            #   … What is therefore missing is the OPERAND's DECLARED type,
            #   and nothing in this unit states one: … Its operand is declared
            #   '__mlir_type.index', which is ONE 64-bit word here …
            #
            # Measured on a program this unit DOES declare the field for —
            # `struct S: var _mlir_value: __mlir_type.index`, whose
            # `pop.cast_to_builtin[_type=__mlir_type.index](self._mlir_value)`
            # is a `_self`-spelled operand the reader resolves through
            # `MLIR_SELF_TYPE_NAMES` (`mlir_operand_declared_type`). Both
            # architectures, byte-identical. It is the same disease this
            # document is about, one branch over: a diagnostic that cannot see
            # a fact it now has, and here it cannot see it while the very next
            # sentence in the same string states it.
            #
            # So the missing piece is the OPERATION, and it is named rather
            # than waved at: `mlir_dialect_cast_advice` is the reader that says
            # what each operation would become, and it is asked here so the
            # refusal and the table cannot disagree about which operations are
            # answerable — which is the reason it is one function rather than a
            # sentence written out.
            tail = (" The RESULT is one word and the OPERAND is a word too, so "
                    "what is missing is neither a representation nor a "
                    "declaration: it is this OPERATION, which is not one of the "
                    "spellings this path rewrites."
                    + mlir_dialect_cast_advice(op, bracket, operand))
        elif rkind == "vector":
            tail = (" What is therefore missing is a REPRESENTATION of an "
                    "N-lane vector — the buffer those lanes would live in, "
                    "which this path does not build — and that is a different "
                    "thing from a type. A deliberate deferral, not an "
                    "impossibility: the operation is nameable and its result is "
                    "nameable too, so nothing here is a claim that the "
                    "construct cannot be written down.")
        else:
            tail = (" This path's only value is a 64-bit word, so the "
                    "result's width and element type are a fact it has no "
                    "source for. A deliberate deferral, not an impossibility: "
                    "read the bracket at the use site instead.")
        return (
            f"`{op}` is a dialect OPERATION whose RESULT TYPE is written in its "
            f"own bracket — as `_type=`, or as a predicate, bin_op, mask, "
            f"ordering or discriminant beside it — and that bracket holds a "
            f"DIALECT object (`__mlir_type.…`, `__mlir_attr.`#kgen.…``) rather "
            f"than a value."
            + mlir_result_clause(bracket)
            + tail
            + mlir_operand_clause(operand)
        )
    if op in MLIR_ELEMENTWISE_OPS:
        return (
            f"`{op}` is a dialect OPERATION applied ELEMENTWISE, so whether it "
            f"denotes one 64-bit word — the only value this path has — or an "
            f"N-lane vector is a fact about its OPERANDS' type and not about "
            f"the operation's name: for a scalar operand both architectures "
            f"already emit the same computation for the ORDINARY spelling of "
            f"this one, and for a SIMD operand the result is a vector of N "
            f"lanes, which is not a word at all."
            + mlir_operand_clause(operand)
            + ("" if mlir_type_kind(operand) is not None else
               " Nothing in the source states a type for this operand, and a "
               "DECLARATION is what this path reads, so establishing one is "
               "the missing piece.")
            + ("" if mlir_type_kind(operand) != "word" else
               " What is missing is therefore the OPERATION rather than the "
               "type: this path rewrites a dialect operation to the ordinary "
               "spelling only where the ordinary spelling computes the same "
               "thing, and this one is not among them — `pop.max` is a "
               "saturating, NaN-aware selection and is not "
               "`a if a > b else b`, `pop.abs` is not `-a` on the saturating "
               "cases, and `pop.div` does not say WHICH of the two divisions it "
               "is, which is the question `pop.floordiv` and `index.divs` "
               "between them answer: this path's `//` FLOORS and its `/` "
               "truncates, both measured, so the two are different rewrites "
               "rather than one. `pop.floordiv` is absent for the weaker "
               "reason that no site in the corpus reaches it, which is a "
               "deliberate non-widening rather than a gap.")
            + " A deliberate deferral, not an impossibility"
        )
    if op.startswith(MLIR_VECTOR_OPS_PREFIX):
        return (
            f"`{op}` is a dialect OPERATION over a VECTOR — its operand is "
            f"`!kgen.simd<LENGTH, DTYPE>` and its result is N lanes, where this "
            f"path's only value is one 64-bit word, so the element width and "
            f"the lane count are a fact it has no source for. A deliberate "
            f"deferral, not an impossibility: the operation is nameable and its "
            f"operands are values, so what is missing is a representation of "
            f"the vector, not of a word"
        )
    return (
        f"`{op}` is a dialect OPERATION, and this path has no lowering table "
        f"for dialect operations: it lowers a Mojo program to a Mach-O image "
        f"whose only value is a 64-bit word, and no instruction selection here "
        f"knows what this operation denotes. Refused by name rather than read "
        f"out of a register, which is what produced 10 on arm64 and 0 on "
        f"x86-64 for one source"
    )
    # A NAME-keyed "this operation denotes one 64-bit word, so write the
    # ordinary spelling" table is DELIBERATELY not here, and this is the place
    # that says so, because a version of this function did carry one and it was
    # wrong: `MLIR_EFFECT_OPS` above and the operation-vs-operand-type census
    # both exist because the answer to "is this operation's result a
    # word?" is a fact about its OPERANDS, not its name — 26 of the 38
    # arithmetic sites are elementwise over an N-lane vector, and a name-keyed
    # table would have lowered those to a scalar add of two vector-typed words.
    # That branch was UNREACHABLE (a `return` above ended the function), so it
    # never fired and never raised the `NameError` its undefined
    # `MLIR_WORD_VALUED_OPS` would have; deleting it is a deletion and not a
    # behaviour change, and `test_formal_mlir_precedence.py`'s
    # `no_dialect_table_is_keyed_on_the_operation_name_alone` is what keeps a
    # reader from putting it back. A real table has to read the operand's
    # declared type first, which is the next step that document names.


def mlir_dialect_refusal(name: str, op: str = None,
                         operand: str = None, bracket=None) -> str:
    """The refusal for a bare `__mlir_*` name that no template rule covers.

    `__mlir_op` is the one the template set does not list, and it is the one
    real stdlib source reaches: `std/builtin/value.mojo:203` and
    `std/sys/debug.mojo:20` both spell `__mlir_op.`lit.…`[...](…)`. The
    template rules (`is_mlir_template`) key on a fixed set of NAMES and are
    right to — `__mlir_op` is an OPERATION BUILDER, not an attribute or type
    template, and calling it a template would misdescribe it.

    `op` is the OPERATION the name is applied to, when the call site knows it
    (`mlir_dialect_op_name`), and it is what decides WHICH of the three
    refusals in `mlir_dialect_op_refusal` applies. Without it the message falls
    back to naming the `__mlir_` prefix and saying what is missing for the
    family, which is all a caller with only the root name can honestly say.

    `operand` is the operation's first operand's DECLARED type spelling, when
    the call site could read one (`mlir_operand_declared_type`), and `bracket` is
    the operation's own subscript when it has one. Neither changes a CLASS — the
    census in `mlir_dialect_op_refusal` is unchanged by either — and each only
    lets the message report a type this build established instead of saying it
    has none.

    The alternative to refusing by name at all was worse and was measured: an
    unrecognised `__mlir_*` name has no binding, so `formal/build.py`'s name
    check refused it as "no home", which names a SYMPTOM of the register
    fall-through and sends the reader to the allocator instead of to the
    construct. Both of those files lost their place in the sweep's coverage for
    a reason that is about MLIR."""
    if op is not None:
        return mlir_dialect_op_refusal(op, operand, bracket)
    return (
        f"{name} is an MLIR dialect construct: this path has no MLIR, so it "
        f"lowers a Mojo program to a Mach-O image whose only value is a "
        f"64-bit word, and a dialect attribute, type or operation has no "
        f"template for that word to assemble from — the "
        f"fragment-and-sub-expression template would have to become a "
        f"container, and a container here is a blob in the frame of the "
        f"function that built it, which disagrees with the compiler that does "
        f"have MLIR. Refused by name rather than read out of a register, "
        f"which is what produced 10 on arm64 and 0 on x86-64 for one source. "
        f"Write the value the construct denotes at the use site"
    )


def is_mlir_template(e) -> bool:
    """True when `e` is an MLIR attribute/type TEMPLATE, in any spelling.

    Keys on the BASE NAME alone, and that is the whole of the fix. It used to
    be reached only for a MULTI-ELEMENT subscript, so the two other spellings
    of the identical construct — the dotted one,
    `__mlir_attr.`#kgen.param.expr<…>``, and the single-element bracket,
    `__mlir_type[x]` — fell through to the ordinary member-read / subscript
    lowering, which reads a name nothing defined and produces whatever word is
    in the register. That is not a wrong answer, it is a FABRICATED one, and it
    had three properties that made it the worst output of this path:

      * three different templates (including a deliberately bogus one) all
        produced the same number, because the template is never read;
      * the two architectures disagreed — arm64 printed 10 and x86-64 printed 0
        for the same source, which no arch-free refusal text can prevent
        because there was no refusal to share;
      * the number was PROGRAM-SHAPE dependent (adding five locals changed it
        to 1), so it could not even be mistaken for a stable wrong answer that
        a test might accidentally agree with.

    A template is a template however it is spelled, so the check is on the
    base and the arity is not consulted. `MemberExpr` is included because that
    is the spelling real stdlib source uses (`std/sys/info.mojo:32`,
    `std/builtin/type_aliases.mojo:146/149/153`)."""
    if not isinstance(e, (F.SubscriptExpr, F.MemberExpr)):
        return False
    return _base_name(e.obj) in MLIR_TEMPLATE_NAMES


def mlir_template_spelling(e) -> str:
    """How the source spelled this template, for a diagnostic.

    A multi-element bracket gets the element list (`__mlir_type[`!lit.origin<`,
    1, `>`]`) because that is the shape the original refusal was written for and
    the reader is looking for those fragments. `_spell` on its own would render
    that subscript `__mlir_type[…]`, which names the construct but not enough of
    it to find in the file. The dotted and single-element spellings have no
    comma list, and `_spell` already renders both exactly as written."""
    if isinstance(e, F.SubscriptExpr) and is_multi_index(e.index):
        return multi_index_spelling(e)
    return _spell(e)


def is_mlir_type_template(e) -> bool:
    """True when `e` is a `__mlir_type` / `__mlir_deferred_type` TEMPLATE.

    The two halves of `MLIR_TEMPLATE_NAMES` are different things and the
    refusal used to call both of them an ATTRIBUTE, which is false of half of
    them: `__mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`` is an
    attribute and `comptime _TargetType = __mlir_type.`!kgen.target`` (which is
    what `std/sys/info.mojo` declares) is a TYPE. A type is not a value a
    register could hold, so it is refused as a type — and the message has to
    say that, because the sibling `target_get_field` on the SAME target does
    answer, and a reader told "there is no MLIR on this path" for the type
    would be sent looking for a missing MLIR rather than for a type."""
    return _base_name(getattr(e, "obj", None)) in MLIR_TYPE_TEMPLATE_NAMES


def mlir_type_template_refusal(e) -> str:
    """The refusal for an MLIR TYPE template. Distinct from the attribute one."""
    return (
        f"{mlir_template_spelling(e)} names an MLIR TYPE, not a value: the "
        "template's elements are backtick-quoted type fragments and the whole "
        "thing denotes a type, and a type is not something a register can hold "
        "on a path where the only value is a 64-bit word. Refused rather than "
        "read out of a register, which would give a program a number no source "
        "wrote."
    )


def mlir_template_refusal(e):
    """The refusal for an MLIR template in any spelling, or None if `e` is not one.

    The text is `multi_index_refusal`'s, unchanged and still ARCH-FREE: it was
    already correct for the one spelling that reached it, and the defect was
    that the other two spellings did not. Naming the construct — not the
    symptom — is what makes it usable on a file nobody has read.

    A template that ASKS THE TARGET A QUESTION is not this refusal: the
    target-query evaluator below answers it, because a formal image is compiled
    for one known target and the question has exactly one right answer for it.
    That check comes first and it comes from here rather than from either
    backend, so arm64 and x86-64 cannot disagree about whether a given
    `__mlir_attr[...]` is answerable."""
    if not is_mlir_template(e):
        return None
    if is_mlir_type_template(e):
        return mlir_type_template_refusal(e)
    answered = target_template(e)
    if answered is not None and answered[0] in ("value", "unanswered"):
        return answered[1] if answered[0] == "unanswered" else None
    if answered is not None and answered[0] == "target":
        return target_value_refusal(e)
    return multi_index_refusal(MULTI_INDEX_MLIR_TEMPLATE,
                               mlir_template_spelling(e))




# ── Build-time target queries ─────────────────────────────────────────────
#
# `formal/model.py` refuses every MLIR attribute template on the ground that
# "there is no MLIR on this path for the template to become". That ground is
# right about a DIALECT ATTRIBUTE — `#kgen.simd<1>`, `#pop.float_literal<nan>`,
# `#lit.struct<{…}>` — and wrong about the one family whose meaning is not an
# MLIR object at all: a `#kgen.param.expr<…>` TARGET QUERY.
#
# `std/sys/info.mojo` is built entirely out of them, and it is the module that
# 35 of the 46 files in this family are blocked behind:
#
#     comptime _TargetType = __mlir_type.`!kgen.target`
#     def _current_target() -> _TargetType:
#         return __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`
#     def __arch() -> __mlir_type.`!kgen.string`:
#         return __mlir_attr[
#             `#kgen.param.expr<target_get_field,`, Self.value,
#             `, "arch" : !kgen.string`, `> : !kgen.string`]
#
# A formal image is compiled for ONE target and that target is stated by the
# build itself: `compile_formal(arch=…, fmt=…)` is about to emit an arm64 (or
# x86-64) Mach-O (or ELF) for this machine. "What is the current target's arch"
# therefore has exactly one correct answer for this build, and answering it at
# build time is not a guess — it is the same fact the linker is about to act on.
# What the backend CANNOT answer is equally decidable, and is refused: a CPU
# feature (`target_has_feature`) is a property of a CPU the build never names,
# and a field the backend has no source for (`"triple"`, `"stdlib_plugin"`)
# would be a string this file never wrote. See `Target.field`.
#
# Everything here is leaf-most on purpose: `os` and `fire_compiler` only, like
# the rest of this module, so the two architectures cannot drift on what a
# target query means — the same rule `is_mlir_template` and
# `multi_index_refusal` already follow.

# The two halves of `MLIR_TEMPLATE_NAMES`, split because they are refused for
# different reasons. See `is_mlir_type_template`.
MLIR_TYPE_TEMPLATE_NAMES = frozenset(("__mlir_type", "__mlir_deferred_type"))


class Target:
    """The target a formal image is for, and the answers this build can state.

    Every field is DERIVED from the two things the build already commits to —
    the architecture the codegen emits, and the container format it wraps the
    result in — and every one is a fact about the EMITTED IMAGE rather than
    about the machine doing the compiling. That is the whole reason these
    answers are not fabrications: a Mach-O image runs on Darwin whatever host
    emitted it, and the word size of a path this module already describes as
    "one 64-bit word" is 64 whatever the CPU.

    `field(name)` returns None for a field this build has no source for, and
    `unanswerable(name, why)` says which. A hand-kept feature table is exactly
    what that exists to avoid, so there isn't one: `target_has_feature` is
    refused outright rather than answered from a list that would rot into a
    wrong answer nobody could detect.
    """

    __slots__ = ("arch", "fmt", "os", "host_arch", "_fields", "_numerics")

    def __init__(self, arch: str, fmt: str):
        self.arch = arch
        self.fmt = fmt
        # The emitted container decides the OS: a Mach-O image is a Darwin
        # image. `build.default_format` is where the build already makes this
        # choice, and asking for the other format on purpose (a Linux host
        # asking for a Mach-O to exercise the emitter) is a target change, not
        # a contradiction.
        self.os = "darwin" if fmt == "macho" else "linux"
        try:
            self.host_arch = os.uname().machine
        except (AttributeError, OSError):
            self.host_arch = ""
        # `arch` is the backend's own name; the value is the spelling
        # `std/sys/info.mojo`'s `__arch` documents ("x86_64", "aarch64"), which
        # is also what LLVM calls the first one.
        self._fields = {
            "arch": {"arm64": "aarch64", "x86_64": "x86_64"}[arch],
            "os": self.os,
            # Both architectures this backend emits are little-endian, and that
            # is a property of the architecture name rather than of the host.
            "endianness": "little",
        }
        self._numerics = {
            # "a formal value is one 64-bit word" is this module's own model
            # of every value it handles, and an `index` IS a pointer width.
            "pointer_width": 64,
            # 128 is the vector register width of both architectures: NEON on
            # AArch64, and the baseline XMM/YMM pair on x86-64.
            "simd_bit_width": 128,
        }

    def field(self, name: str):
        """The value of the string-valued target field `name`, or None."""
        return self._fields.get(name)

    def numeric_field(self, name: str):
        """The value of the integer-valued target field `name`, or None."""
        return self._numerics.get(name)

    def is_cross_compilation(self) -> bool:
        """True when the emitted image is not for the machine that built it.

        Measured, not assumed: the codegen names the architecture it is about
        to emit and `os.uname()` names the one running, so `--arch=x86_64` on
        an arm64 Mac is cross-compiling and the default arm64 build is not.
        `std/gpu/host/compile.mojo` asks exactly this (`cross_compilation`),
        and a build that answered it from a constant would be wrong for half
        the backend's own configurations."""
        return bool(self.host_arch) and self.host_arch != self.arch

    def describe(self) -> str:
        return (f"{self.arch}/{self.os} (a {self.fmt} image for "
                f"{self.host_arch or 'an unknown host'})")

    def __repr__(self) -> str:
        return f"Target({self.arch!r}, {self.fmt!r})"


def target_for(arch: str, fmt: str) -> Target:
    """The `Target` for an image of `arch` in `fmt`."""
    return Target(arch, fmt)


_TARGET: Target = None


def publish_target(t: Target) -> None:
    """Install `t` as the current build's target.

    Published rather than threaded, and for the reason `publish_module_symbols`
    is: the consumers are a node walk with no unit in hand (the module-symbol
    folder, the function-body rewrite) and the evaluator they call, and neither
    has an `arch` to be handed. Replaces, never merges — a dylib and its
    dependent are compiled for the same target, and a table that accumulated
    both would be a target that is neither."""
    global _TARGET
    _TARGET = t


def target() -> Target:
    """The published `Target`, or None before anything published one.

    None is NOT "unknown target, answer nothing": every caller treats it as
    "there is no build to fold against", which is what makes a query refuse
    with its own reason rather than with a fabricated default."""
    return _TARGET


# The `#kgen.param.expr<OP, …>` operations this evaluator answers, and the
# REASON each one is answerable or not. A name absent from both tables is
# refused, and the refusal quotes the operation — which is the one piece of
# information the reader needs and did not have.
#
# Each entry is (arity, evaluator). Zero-arg operations are `current_target`,
# `cross_compilation` and `accelerator_arch`; the rest take their operands from
# the template's own argument list.
_TARGET_QUERY_OPS = {
    "current_target": (0, None),
    "target_get_field": (2, "_op_target_get_field"),
    "target_has_feature": (2, "_op_target_has_feature"),
    "eq": (2, "_op_eq"),
    "add": (2, "_op_add"),
    "cross_compilation": (0, "_op_cross_compilation"),
    "accelerator_arch": (0, "_op_accelerator_arch"),
}

# A `#kgen.param.expr<…>` result TYPE and the Python type that type is. The
# declared type is checked against the value the evaluator produced, so a fold
# that produced a number for a `!kgen.string` is a refusal rather than a wrong
# answer — the check is what makes "correct values" mean anything.
_TARGET_RESULT_TYPES = {
    "!kgen.string": str,
    "index": int,
    "i64": int,
    "i32": int,
    "i1": bool,
    "!kgen.scalar<bool>": bool,
    "!kgen.target": "target",
}


def _backtick_text(name: str):
    """The literal inside a backtick-quoted fragment, or None if not one."""
    if isinstance(name, str) and len(name) >= 2 and name[0] == "`" \
            and name[-1] == "`":
        return name[1:-1]


def _template_fragments(e):
    """(text, holes) for an MLIR template node in any spelling.

    `text` is the backtick fragments concatenated with a `{n}` placeholder for
    each sub-expression, so the whole template is one string plus a list of
    sub-expressions regardless of how the source wrapped it. That is what makes
    the evaluator indifferent to the wrapping: `std/sys/info.mojo` splits one
    query across four lines, the same query written on one line parses the
    same way, and a line-continuation-style concatenation cannot make the two
    disagree.

    Returns None for a node that is not a template at all, or whose elements
    are not all either a backtick fragment or a sub-expression the caller can
    evaluate — which is itself an answer: this path cannot read the template."""
    base = _base_name(getattr(e, "obj", None))
    if base not in MLIR_TEMPLATE_NAMES:
        return None
    if isinstance(e, F.MemberExpr):
        text = _backtick_text(e.member)
        return None if text is None else (text, [])
    if not isinstance(e, F.SubscriptExpr):
        return None
    index = e.index
    if isinstance(index, (F.TupleExpr, F.ListExpr)):
        elements = list(index.elements)
    else:
        elements = [index]
    out = []
    holes = []
    for el in elements:
        if base in MLIR_TYPE_TEMPLATE_NAMES and isinstance(el, F.IdentExpr):
            # A TYPE template's elements are type fragments, and a hole in one
            # is a type expression this path cannot evaluate.
            return None
        if isinstance(el, F.IdentExpr):
            text = _backtick_text(el.name)
            if text is None:
                holes.append(el)
                out.append("{%d}" % (len(holes) - 1))
                continue
            out.append(text)
            continue
        if base in MLIR_TYPE_TEMPLATE_NAMES:
            return None
        holes.append(el)
        out.append("{%d}" % (len(holes) - 1))
    return "".join(out), holes


# The prefix every "this build cannot answer that" sentence carries, and the
# reason it is a constant rather than a habit: `tools/formal_sweep.py` buckets
# findings by a marker substring, and three separate wordings for one class of
# limit would put three of them in whatever matched next — which is how
# `no_public_api_reason`'s three false branches happened. One marker, one
# family, and the sentence after it is free to be as specific as the case is.
TARGET_QUERY_UNANSWERED = "this build cannot answer this target query:"


def _unanswered(why: str) -> tuple:
    return ("unanswered", TARGET_QUERY_UNANSWERED + " " + why)


def _split_top_level(text: str, sep: str) -> list:
    """`text` split on `sep` outside quotes and outside <>/()/[] nesting."""
    parts = []
    depth = 0
    in_quote = False
    start = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if in_quote:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_quote = False
        elif ch == '"':
            in_quote = True
        elif ch in "<([{":
            depth += 1
        elif ch in ">)]}":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return parts


def _unquote(token: str):
    """A `"…"` token's text, or None if `token` is not one."""
    token = token.strip()
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return None


def _arg_operand(token: str, holes: list, tgt: Target):
    """One argument of a target query: its value, the target marker, or None.

    Four shapes occur in the corpus, and the fourth is why this is a function
    rather than a lookup. A `{n}` hole is a sub-EXPRESSION: either another
    query, recursively (that is how `target_get_field` receives the nested
    `#kgen.param.expr<current_target>` the source wrote inside it) or an
    ordinary literal, which is the common case — `#kgen.param.expr<eq, 1, 2>`
    in `test_formal_run.py` and `` + 1 `` inside an `add` in
    `std/_plugin/selector.mojo` are both literals the source wrote beside the
    fragments. A `"…"` token is a string literal. Anything else is a bare MLIR
    token, of which only an integer and the two boolean spellings have a value
    on this path; a type or an operation name in argument position has none, and
    saying so is the honest answer rather than dropping it."""
    token = token.strip()
    if not token:
        return None
    if token[0] == "{" and token[-1] == "}" and token[1:-1].isdigit():
        idx = int(token[1:-1])
        if idx >= len(holes):
            return None
        hole = holes[idx]
        got = target_template(hole, tgt)
        if got is not None:
            # A value, or the target marker. `unanswered` is None here because
            # the caller reports the OUTER reason, and the inner one is a
            # sub-expression of an argument the outer query cannot be answered
            # without.
            return None if got[0] == "unanswered" else got[1]
        if isinstance(hole, F.BoolLiteral):
            return bool(hole.value)
        return fold_literal_expr(hole)
    lit = _unquote(token)
    if lit is not None:
        return lit
    if token == "true":
        return True
    if token == "false":
        return False
    if token.lstrip("+-").isdigit():
        return int(token)
    return None


def _op_target_get_field(args: list, tgt: Target):
    """`target_get_field(TARGET, "field")` — the field this build can state."""
    if not isinstance(args[0], Target):
        return _unanswered(
                "the first argument of target_get_field is not the current "
                "target, and this build can only read a field of the target it "
                "is emitting")
    name = args[1]
    if not isinstance(name, str):
        return _unanswered(
                "the second argument of target_get_field is not a field name, "
                "so there is no field to read")
    value = tgt.field(name)
    if value is None:
        value = tgt.numeric_field(name)
    if value is None:
        return _unanswered(target_field_refusal(name, tgt))
    return ("value", value)


def target_field_refusal(name: str, tgt: Target) -> str:
    """Why target field `name` has no answer on this path."""
    return (
        f'the current target {tgt.describe()} has no {name!r} for this build to '
        f"state: the field is a property of a target DESCRIPTION, and the only "
        f"facts this build commits to are the architecture it emits and the "
        f"container it wraps it in. Which of those two the field would need is "
        f"not decidable from the source, and a plausible string here is a "
        f"number the program never wrote."
    )


def _op_target_has_feature(args: list, tgt: Target):
    """`target_has_feature(TARGET, "feature")` — refused, and that is the point.

    A CPU feature is a property of a CPU. The build names the architecture it
    emits and never names a CPU, and there is no feature database on a path
    that links libSystem and nothing else — so the two rules that could answer
    it without a database ("a feature of another architecture is impossible"
    and "one this architecture mandates is present") would still leave every
    optional extension undecided, and answering those two while refusing the
    rest would be a hand-kept table pretending to be a derivation.

    So the whole operation refuses, with the one fact the reader can act on: it
    is a per-CPU question, and this build has no per-CPU input. It is
    `std/sys/info.mojo`'s `_has_feature`, and it is the reason that module does
    not build even with every field query answered — one of the TWO permanent
    refusals in that module, the other being `current_target` read as a value;
    both are tabulated in FORMAL_known_limits.md §2.0, which is where that
    module's residue is recorded."""
    if not isinstance(args[0], Target) or not isinstance(args[1], str):
        return _unanswered(
                "a CPU feature is a property of a CPU, and this build names "
                "the architecture it emits and never a CPU")
    return _unanswered(
            f"target_has_feature({args[1]!r}) is a per-CPU question: a CPU "
            f"feature is a property of a CPU, and this build names the "
            f"architecture it emits and never a CPU, so there is no feature "
            f"database here to answer it from — and a hand-kept one would rot "
            f"into a wrong answer that no test could see")


def _op_eq(args: list, tgt: Target):
    """`eq(a, b)` — equality of two values that both already folded."""
    if isinstance(args[0], Target) or isinstance(args[1], Target):
        return _unanswered(
                "eq compares two values, and one of them is the current target "
                "attribute, which has no value on this path")
    try:
        return ("value", args[0] == args[1])
    except Exception:
        return _unanswered("eq's operands are not comparable here")


def _op_add(args: list, tgt: Target):
    """`add(a, b)` on two integers that both already folded."""
    if not (isinstance(args[0], int) and isinstance(args[1], int)) \
            or isinstance(args[0], bool) or isinstance(args[1], bool):
        return _unanswered(
                "add is integer addition on this path, and at least one "
                "operand is not an integer this build could fold")
    return ("value", args[0] + args[1])


def _op_cross_compilation(args: list, tgt: Target):
    return ("value", tgt.is_cross_compilation())


def _op_accelerator_arch(args: list, tgt: Target):
    """`accelerator_arch` — "" for an image with no accelerator on the link line.

    `std/sys/info.mojo`'s own docstring states the contract: "If there is no
    accelerator on the system, this function returns an empty string." A formal
    image links the platform C library and nothing else — there is no CUDA
    runtime, no Metal device, no plugin — so the answer is the empty string and
    it is a fact about the link line rather than about the source."""
    return ("value", "")


def _parse_param_expr(text: str):
    """(op, arg_texts, result_type) for a `#kgen.param.expr<…> : T` template.

    None for anything else, including a template that is not a param expr at
    all (`#kgen.simd<1>`, `#pop.float_literal<nan>`, `#index<cmp_predicate
    ult>`) — those are dialect attributes whose meaning is an MLIR object, and
    `is_mlir_template` refuses them with the MLIR wording."""
    text = text.strip()
    prefix = "#kgen.param.expr<"
    if not text.startswith(prefix):
        return None
    depth = 0
    in_quote = False
    end = -1
    i = len(prefix) - 1
    while i < len(text):
        ch = text[i]
        if in_quote:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_quote = False
        elif ch == '"':
            in_quote = True
        elif ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
            if depth == 0:
                end = i
                break
        i += 1
    if end < 0:
        return None
    body = text[len(prefix):end]
    tail = text[end + 1:].strip()
    result_type = None
    if tail.startswith(":"):
        result_type = tail[1:].strip()
    elif tail:
        return None
    parts = _split_top_level(body, ",")
    op = parts[0].strip()
    if not op:
        return None
    return op, [p.strip() for p in parts[1:]], result_type


def target_template(e, tgt: Target = None):
    """What an MLIR template node means for a build targeting `tgt`.

    None when `e` is not a template this evaluator reads. Otherwise a
    four-valued answer, because four things are true and a two-valued one
    would have to lie about two of them:

      * `("value", v)` — `v` is the int / bool / str the query denotes for this
        target, and `v` may legitimately be `False`, `0` or `""`, which is why
        this is not `(v or None)`.
      * `("target", t)` — the current TARGET itself. Not a value: the target
        attribute has no representation on this path. It is still an answer,
        because the next query in the same template takes it as an argument
        (`target_get_field<current_target, "arch">`), and refusing the inner
        one would refuse an outer one this build CAN answer.
      * `("unanswered", why)` — a query about the target that this build has no
        honest answer to, with the reason, so the caller can refuse with a
        sentence that names the missing fact instead of the construct.
      * `None` — not a query about the target at all: a dialect attribute, or
        something that is not a template.
    """
    if tgt is None:
        tgt = _TARGET
    if tgt is None:
        return None
    frag = _template_fragments(e)
    if frag is None:
        return None
    text, holes = frag
    parsed = _parse_param_expr(text)
    if parsed is None:
        return None
    op, arg_texts, result_type = parsed
    entry = _TARGET_QUERY_OPS.get(op)
    if entry is None:
        return None
    arity, impl = entry
    if arity != len(arg_texts):
        return _unanswered(
                f"the {op!r} query is written here with "
                f"{len(arg_texts)} argument(s) and this path knows it with "
                f"{arity}, so it will not guess what the operands mean")
    # An argument may carry its own type annotation (`"arch" : !kgen.string`),
    # which describes the operand and is not itself an operand.
    operands = []
    for arg_text in arg_texts:
        operand = _arg_operand(arg_text.split(" : ")[0], holes, tgt)
        if operand is None:
            return _unanswered(
                    f"an argument of the {op!r} query is neither a literal nor "
                    f"another query this build can read. The whole query reads "
                    f"{_spell_template(frag)}.")
        operands.append(operand)
    if impl is None:
        # The one operation that is a value only as an argument.
        if result_type not in (None, "!kgen.target"):
            return _unanswered(
                    f"the {op!r} query is declared to produce "
                    f"{result_type} and the current target is a target, not a "
                    f"{result_type}")
        return ("target", tgt)
    result = globals()[impl](operands, tgt)
    if result[0] != "value":
        return result
    value = result[1]
    if result_type is not None:
        want = _TARGET_RESULT_TYPES.get(result_type)
        if want is None:
            return _unanswered(
                    f"the {op!r} query declares a result of "
                    f"{result_type}, and this path has no type to lower that "
                    f"to — refusing rather than materializing the value as "
                    f"something the source did not declare")
        if want == "target" or isinstance(want, type) \
                and not isinstance(value, want):
            return _unanswered(
                    f"the {op!r} query declares a result of "
                    f"{result_type} but evaluates to "
                    f"{type(value).__name__}, which is a different value than "
                    f"the source declared, so it is refused rather than "
                    f"materialized as one")
    return ("value", value)


def _spell_template(frag) -> str:
    """One template rendered the way the source wrote it, holes included.

    A diagnostic that quotes the evaluator's internal `{0}` placeholder tells
    the reader nothing they can find in their file, which is the one thing a
    message about a source construct has to do. This renders the fragments and
    the sub-expressions together, so the sentence names the query the way the
    author wrote it."""
    text, holes = frag
    for i, hole in enumerate(holes):
        text = text.replace("{%d}" % i, _spell(hole), 1)
    return text.replace("`", "")


def fold_target_template(e, tgt: Target = None):
    """The int / bool / str a target query denotes for this build, or None.

    The convenience read for a caller that wants the value and has its own
    refusal for None: a module-level `comptime` binding that folds, and a
    function body the shared rewrite replaces with a literal."""
    got = target_template(e, tgt)
    if got is not None and got[0] == "value":
        return got[1]
    return None


def template_is_answered(e) -> bool:
    """True when this build CAN answer `e`, so nothing inside it is still open.

    The rule both walks over a template tree use, in one place because two
    copies of it is how the same construct came to be answered in one position
    and refused in another. It matters for the NESTED case rather than the
    obvious one: `std/sys/info.mojo` writes its field queries with
    `#kgen.param.expr<current_target>` as an ARGUMENT, and that inner node on
    its own is a target-as-a-VALUE, which is a refusal. With the outer query
    answered, the inner node is not a use at all — it is part of a question
    already answered — so a walk that visited it and refused would reject a
    construct the build handles. Measured, not reasoned: that is exactly the
    failure `std/sys/info.mojo`'s `_os` and `__arch` hit, one of which is the
    whole reason this exists."""
    return is_mlir_template(e) and fold_target_template(e) is not None


def iter_templates_preorder(node):
    """Every template in `node`'s tree, outermost first, stopping at an answered one.

    The single walking rule for the MLIR-template family, shared by the
    module-level refusal here and `formal/build.py`'s function-body rewrite,
    because the two were once the same walk written twice and disagreed: the
    refusal visited the nested `#kgen.param.expr<current_target>` inside a
    field query and refused a construct the evaluator answers. One rule, one
    place, and neither caller can reach a node the other would have skipped.
    """
    if template_is_answered(node):
        return
    if is_mlir_template(node):
        yield node
        # A template's own elements are backtick fragments and sub-expressions.
        # Those are walked, so a query nested in a query is still seen, but an
        # `__mlir_type` template's elements are TYPE fragments and nothing
        # inside one is a value this path can read.
        if not is_mlir_type_template(node):
            frag = _template_fragments(node)
            for hole in (frag[1] if frag else ()):
                for inner in iter_templates_preorder(hole):
                    yield inner
        return
    if isinstance(node, (list, tuple)):
        # A tuple as well as a list, and not as a generality: a call's KEYWORD
        # arguments are a list of `(name, value)` pairs — `CallExpr.kwargs` — and
        # `std/builtin/type_aliases.mojo` puts its templates under one
        # (`Origin[0, _mlir_origin=__mlir_attr[…]]()`). A walk that descends only
        # into lists reads past them and reports a module as clean, which is the
        # false-PASS shape this whole walk exists to prevent.
        for child in node:
            for inner in iter_templates_preorder(child):
                yield inner
        return
    if node is None or isinstance(node, (str, int, float, bool)):
        return
    for name in getattr(node, "__dataclass_fields__", {}):
        for inner in iter_templates_preorder(getattr(node, name)):
            yield inner


def target_value_refusal(e) -> str:
    """The refusal for a template whose VALUE is the current target itself.

    The target is not a value on this path, and this is the one place in the
    family where the MLIR wording was actively misleading: the same file's
    `target_get_field` on the same target DOES answer, so a reader told "there
    is no MLIR on this path" for `current_target` would look for a missing MLIR
    instead of for a value that has no representation. The message therefore
    says what would work."""
    spelled = mlir_template_spelling(e)
    return (
        f"{spelled} asks for the current TARGET itself, which is not a value on "
        f"this path: a target is a description of what to compile for, it has no "
        f"64-bit-word representation, and materializing one would put a pointer "
        f"to a frame blob where the source wrote a target. Refused as a VALUE "
        f"and nothing else — the same target's FIELDS are answerable, and "
        f"'target_get_field' on it is how a program asks this build what it is "
        f"compiling for."
    )


def target_query_refusal(e, tgt: Target = None):
    """The refusal for a target query this build cannot answer, else None."""
    got = target_template(e, tgt)
    if got is not None and got[0] == "unanswered":
        return got[1]
    return None


def refuse_module_level_mlir_templates(stmts) -> None:
    """Raise `CodegenError` if a module-level `comptime` binding's initializer
    contains an MLIR template. Called first by BOTH backends' `compile()`.

    A module-level `comptime X = …` is a compile-time binding, and the
    expression walk that refuses MLIR templates runs over FUNCTION bodies only:
    `compile()` picks `FunctionDef`s out of the module statement list and
    lowers nothing else. So the one construct the refusal exists for —
    `comptime OriginSet = __mlir_type[`!lit.origin<`, 1, `>`]` — was written,
    compiled away without a word, and every later `var v = OriginSet` read a
    name with no definition. It built, it ran, and it printed a fabricated
    word: 10 on arm64, 0 on x86-64, for the same source. That is a FALSE PASS
    in the strongest sense the project has — `std/builtin/type_aliases.mojo`
    declares four such bindings (lines 146/149/153/157) and was counted in the
    sweep's coverage as a file that built.

    The walk RECURSES, because the templates are not always the initializer's
    top node: in that same file the `__mlir_attr[…]` templates sit two levels
    down, inside a call's keyword argument
    (`Origin[0, _mlir_origin=__mlir_attr[…]]()`).

    What is missing is the walk's REFUSALS, not its lowering: this function
    decides nothing about what a module-level `comptime` binding means, and a
    module-level `comptime n = len(xs)` over a runtime parameter is still
    outside both backends rather than newly refused here. MLIR templates are
    the one refusal that is decidable with no value context and no type
    inference — the base NAME is the whole of the test — which is why this one
    closes and the rest do not.

    Called from `formal/build.py:_prepare_functions`, which is the ONE pipeline
    both front ends (executable and dylib) hand their parsed module to, so
    there is a single call site rather than one per backend and the two
    architectures cannot name different limits for one construct — the failure
    `limit_comptime_over_a_runtime_parameter` is pinned against.

    It refuses only what is still unanswerable. `mlir_template_refusal` is the
    one reader both the backends and this function ask, and it now returns None
    for a `#kgen.param.expr<…>` target query this build can answer — so
    `comptime ARCH = __mlir_attr[target_get_field<current_target, "arch">]`
    passes here and is FOLDED by `collect_module_symbols` a few lines later,
    which is the module-constant path that already substitutes a folded value
    at every read. A binding the evaluator declines, and a binding that is a
    template about anything other than the target, is refused exactly as
    before.

    The walk is PRE-ORDER and does not descend into a query it can answer, for
    the reason `template_is_answered` gives: `#kgen.param.expr<current_target>`
    appears as an ARGUMENT inside every field query `std/sys/info.mojo` writes,
    and on its own that node is a target read as a value — a refusal. Visiting
    it and refusing would reject the very construct this evaluator exists to
    answer, and the binding that names it is the one the 46-file family hangs
    on. The recursion is kept (it is what catches the templates nested two
    levels down under `Origin[0, _mlir_origin=__mlir_attr[…]]()`), so the rule
    is "stop at an answered query", not "only look at the top node"."""
    for st in stmts:
        value = getattr(st, "value", None)
        if value is None or not isinstance(st, F.ComptimeVarStmt):
            continue
        for node in iter_templates_preorder(value):
            why = mlir_template_refusal(node)
            if why is not None:
                # "attribute" vs "type" is the node's own base name, not a
                # fixed word: `__mlir_type.`!kgen.target`` — which is what
                # `std/sys/info.mojo` declares as `_TargetType` — is a TYPE, and
                # calling it an attribute in a message about that file is a
                # claim about the file that is false.
                kind = "type" if is_mlir_type_template(node) else "attribute"
                raise CodegenError(
                    f"the module-level comptime binding "
                    f"{getattr(st, 'target', '?')!r} is initialized from an MLIR "
                    f"{kind} template: {why} Module-level `comptime` "
                    f"bindings are not part of the function-body expression "
                    f"walk on this path, so nothing used to refuse this and the "
                    f"binding read as an undefined name at every use site.")
    return None


def subscript_index_is_a_comptime_parameter_list(e, structs_by_name=None,
                                                 callee_defs=None,
                                                 own_template_structs=None) -> bool:
    """True when `e`'s bracketed comma list is a COMPILE-TIME PARAMETER list.

    `x[a, b]` and `Foo[A, B]` are ONE node shape and not the same construct,
    and the difference is not cosmetic: the first stores two words in a
    container at run time and the second stores nothing anywhere, because the
    brackets select an instantiation. So every consumer that would otherwise
    read a bracket list as a container has to ask this before it does, and the
    two answers in this file that were false about the second kind are what
    cost it: the escape check's container branch in `formal/build.py`, and
    `multi_index_kind` below, which answered "a subscript whose index is a
    tuple" about a type application. Both were false diagnoses counted in map
    rows 7 and 8 of the sweep work map; `formal/build.py`'s container branch
    and this `multi_index_kind` were two readers of the same wrong question,
    which is why they are one function now.

    THE ONE ANSWER, for the same reason `multi_index_refusal_for` is the one
    reader of the multi-index question: two functions deciding "is this bracket
    list a comptime parameter list" would be two chances to disagree, and the
    disagreement is silent — one of them skips a check the other still runs.

    **Only a base this image can CLASSIFY gets a yes**, and all three classes
    are facts the model already holds rather than readings of the spelling:

      * a bare name in one of the type-constructor tables —
        `type_constructor_kind(name) is not None`, which is `Pointer`,
        `UnsafePointer`, `List`, `Dict`, `Tuple`, `Set`, `Optional`, `SIMD`,
        `Int` and the rest — or in `POINTER_TYPE_CTORS`. These are the
        composite types, and every one of them is spelled with brackets;
      * a bare name `structs_by_name` says THIS MODULE declares. A struct has
        no runtime container representation on this path at all, so a
        subscript on its name cannot be a lookup into one — and this is the
        half that covers a module's OWN generics, which the tables above do not
        name (`_DequeIter[Self.ElementType, origin_of(self), False]` in
        `std/collections/deque.mojo`, `Pair[A, B]`);
      * a bare name `callee_defs` holds a GENERIC `FunctionDef` for, which is
        `multi_index_kind`'s own `generic_callee` test, kept here as well
        because the escape check has no `generic_callee` and would otherwise
        have to re-ask this question without it (`tag[Self.T, origin_of(self)]`);
      * a bare name in `own_template_structs`, THIS unit's own generic struct
        TEMPLATES. They are not in `structs_by_name`, and that is not an
        oversight: `monomorph.without_template_bodies` removes each template
        DECLARATION from the statement list before the pipeline that builds
        `structs` runs, because a template's body has no instantiation in scope
        and analysing it turns a correct generic into a `len(Self.keys)`
        refusal. The declaration has to go, but the NAME is still a
        compile-time parameter list here, so it is handed over separately: the
        document-string claim that `structs_by_name` "covers a module's OWN
        generics" was false for exactly these, and `Tagged[Int, 0]()` in the
        file that declares `Tagged` was answered with the tuple-index sentence —
        about a container lookup the source never wrote.

    Everything else answers **no**, and the caller keeps today's behaviour.
    A single-element index answers no as well, and that is not a gap: a
    one-element bracket is never a container literal, so there is nothing for
    a caller to confuse it with. The multi-element gate lives in
    `is_multi_index` and both callers honour it."""
    if not isinstance(e, F.SubscriptExpr) or not is_multi_index(e.index):
        return False
    name = _base_name(e.obj)
    if name is not None:
        if (type_constructor_kind(name) is not None or name in POINTER_TYPE_CTORS
                or ((callee_defs or {}).get(name) is not None
                    and is_generic(callee_defs[name]))
                or (own_template_structs and name in own_template_structs)):
            return True
        return bool(structs_by_name) and name in structs_by_name
    # Dotted base: e.g. Type.Member[...] or Self.Member[...] or h.tag[...] 
    # where h is an instance (must not be classified). Only classify when the
    # leftmost identifier is a type name this image can classify (declared struct
    # in this module) or is Self (the current type).
    if isinstance(e.obj, F.MemberExpr) and isinstance(e.obj.obj, F.IdentExpr):
        base_ident = e.obj.obj.name
        # Do NOT classify if base is a local/instance variable (not a known type name)
        if base_ident in MLIR_SELF_TYPE_NAMES:
            return True
        if structs_by_name and base_ident in structs_by_name:
            return True
        if own_template_structs and base_ident in own_template_structs:
            return True
        if type_constructor_kind(base_ident) is not None or base_ident in POINTER_TYPE_CTORS:
            return True
        if callee_defs and base_ident in callee_defs and is_generic(callee_defs[base_ident]):
            return True
        return False
    return False


def subscript_is_a_type_application(e, structs_by_name=None,
                                    callee_defs=None) -> bool:
    """True when `e`'s bracket list NAMES an instantiation rather than a value.

    `subscript_index_is_a_comptime_parameter_list`'s question plus
    `external_call`'s own, and nothing else: those are the two bracket lists in
    the language whose elements are compile-time by construction. It is what
    makes the property below transitive — the elements of a TYPE APPLICATION are
    themselves types, all the way down.

    Kept apart from `subscript_index_is_a_comptime_parameter_list` because that
    one is asked about a bracket list this image might have to READ as a value,
    and answering "yes" there is a refusal while answering "yes" here is an
    exemption. Two questions, one predicate, rather than one predicate asked
    twice with the meaning of its answer depending on which reader called it.
    """
    if not isinstance(e, F.SubscriptExpr):
        return False
    if is_external_call_template(e):
        return True
    return subscript_index_is_a_comptime_parameter_list(
        e, structs_by_name, callee_defs)


def type_position_nodes(root, structs_by_name=None, callee_defs=None) -> set:
    """`{id(node)}` for every node of `root` that sits in a TYPE position.

    A type position is REACHED, never guessed from the spelling. The roots are
    the two bracket lists the language makes compile-time by construction
    (`subscript_is_a_type_application`), and from each root the property is
    transitive down the index: the arguments of a type application are types, so
    `external_call["getenv", _CPointer[UInt8, UntrackedOrigin[mut=False]]]`
    puts `_CPointer[…]` and everything under it in a type position.

    **Why the walk has to know.** `iter_nodes` has no parent, so a pass that
    visits every subscript in a body and asks "what does this bracket list mean
    at RUNTIME" reaches the inner `_CPointer[…]` as if it stood alone, and gets
    a true answer about the wrong question: it IS a comptime parameter list, and
    it is also not a runtime subscript, so nothing needs to be said about it.
    Measured before this, on `std/os/env.mojo`'s own three functions:
    `_CPointer[UInt8, UntrackedOrigin[…]] is a compile-time explicit-parameter
    list on a generic, not a subscript`, for a program the backend lowers
    correctly the moment the walk stops asking about a type as a value
    (the multi-parameter-type-in-the-bracket refusal, filed 2026-09 and closed;
    `test_formal_external_call.py` still pins the refusal).

    **What it does not do.** It does not widen `_base_name`, and it does not
    exempt a subscript whose BASE is a value: `h.tag[Int, s]` is a genuine index
    of a genuine value, it is not in a type position, and answering "type
    application" for it would drop a real frame-escape check
    (dotted base bracket lists). Every
    bracket list that is not one of the two compile-time ones keeps today's
    answer, refusal included — "possibly wrong" is the direction this backend
    refuses in everywhere else."""
    out: set = set()

    def absorb(node):
        for n in iter_nodes(node):
            if id(n) in out:
                continue
            out.add(id(n))
            if subscript_is_a_type_application(n, structs_by_name, callee_defs):
                absorb(n.index)

    for node in iter_nodes(root):
        if subscript_is_a_type_application(node, structs_by_name, callee_defs):
            absorb(node.index)
    return out


def multi_index_kind(e, base_is_dict: bool = False,
                     generic_callee=None, structs_by_name=None,
                     callee_defs=None, own_template_structs=None) -> str:
    """What a multi-element subscript index means here. See the section note.

    `e` is the whole `SubscriptExpr`, so the base is available and the answer
    can be about the construct rather than about the index alone.
    `base_is_dict` is the backend's knowledge (a dict literal or a name tracked
    back to one) — the dict-keyed-by-tuples case is the only one lowered.
    `generic_callee` is the FunctionDef the base names, when the backend has
    one in hand and it is a generic; that is what separates a comptime
    parameter list from a value subscript, and it is a fact the backend can
    check rather than a guess from the spelling.
    `structs_by_name` is the same fact for the base being a TYPE rather than a
    function: a generic FUNCTION's bracket list is a comptime parameter list
    (`pick[1, 2]`), and so is a subscript on a type constructor or on a struct
    this module declares (`Pointer[T, origin]`, `_DequeIter[T, origin, False]`).
    The second half was missing, so `Pointer[Int, origin_of(self)]` — four of
    the stdlib's largest container modules — was refused with the tuple-index
    sentence, which is about a container lookup that never happens. Both halves
    answer the same question and are asked through
    `subscript_index_is_a_comptime_parameter_list`, which is the single answer
    for it; both are refusals, so no program that built before this does, and
    the only thing that changes is which true sentence names the construct.
    `own_template_structs` is the same membership test extended to this unit's
    own generic struct TEMPLATES, which are not in `structs_by_name` because
    their declarations are dropped before it is built — see
    `subscript_index_is_a_comptime_parameter_list`.

    A LOWERED `external_call["sym", RetType]` never reaches this function: it
    is answered in `multi_index_refusal_for` above, which returns None for the
    well-formed template and carries the specific sentence for a malformed
    one. This table's kinds are the three ways a multi-element bracket can
    mean something, and `external_call` is a fourth that is not a kind at
    all — it has an answer, not a diagnosis."""
    if base_is_dict:
        return None                       # the one lowered case; not a refusal
    if is_mlir_template(e):
        return MULTI_INDEX_MLIR_TEMPLATE
    if generic_callee is not None and is_generic(generic_callee):
        return MULTI_INDEX_COMPTIME_PARAMS
    if subscript_index_is_a_comptime_parameter_list(e, structs_by_name,
                                                   callee_defs,
                                                   own_template_structs):
        return MULTI_INDEX_COMPTIME_PARAMS
    return MULTI_INDEX_DATA


def multi_index_spelling(e, limit: int = 4) -> str:
    """How the source spelled a multi-element subscript, for a diagnostic.

    `x[a, b, c, …]` past `limit` elements, so a 16-element `external_call[...]`
    does not bury the sentence that says what is wrong with it."""
    n = len(e.index.elements)
    shown = ", ".join(
        _spell(e0) for e0 in e.index.elements[:limit])
    if n > limit:
        shown += ", …"
    return f"{_spell(e.obj)}[{shown}]"


def _spell(node) -> str:
    """A short, readable rendering of one expression, for a message."""
    if isinstance(node, F.IdentExpr):
        return node.name
    if isinstance(node, F.MemberExpr):
        base = _spell(node.obj)
        return f"{base}.{node.member}" if base else node.member
    if isinstance(node, F.IntLiteral):
        return str(node.value)
    if isinstance(node, F.BoolLiteral):
        return "True" if node.value else "False"
    if isinstance(node, F.StringLiteral):
        return repr(node.value)
    if isinstance(node, F.CallExpr):
        return f"{_spell(node.func)}(…)"
    if isinstance(node, F.SubscriptExpr):
        return f"{_spell(node.obj)}[…]"
    if isinstance(node, F.BinaryOp):
        return f"{_spell(node.left)} {node.op} {_spell(node.right)}"
    if isinstance(node, F.UnaryOp):
        return f"{node.op}{_spell(node.operand)}"
    return type(node).__name__


def _comptime_param_element_kind(node, structs_by_name=None) -> str:
    """`'type'` / `'literal'` / `'name'` — what one bracket element IS here.

    **Only claims this call can actually keep.** `'type'` is a positive claim
    backed by a table in this file (`type_constructor_kind`,
    `POINTER_TYPE_CTORS`, the `structs_by_name` this unit compiled, or a
    subscript that is itself a type application), and `'literal'` is one backed
    by the node being an `IntLiteral` / `BoolLiteral` / `StringLiteral` or
    arithmetic over those. Everything else is `'name'`, which is deliberately
    the WEAKEST answer and deliberately means "a bare name this image cannot
    resolve to a declaration" — **not** "not a type".

    That direction is the whole point, and it is the opposite of the reader's
    first guess. `Span[StaticString, ImmStaticOrigin]` — the bracket
    `std/sys/arg.mojo:51` spells — has a first element this call resolves as a
    bare name too, and a message that said "the second is not a type" would be a
    claim this call cannot make: it only knows the name is not in a table it
    holds. So `'name'` says what is knowable, `_UNRESOLVABLE_NAME_SHAPES` says
    which of the two shapes a name can be — a type this image could not resolve,
    or a `comptime` alias whose initializer does not fold — and the second of
    those is measured on the second element of exactly this bracket list.
    """
    if isinstance(node, F.SubscriptExpr):
        # `subscript_is_a_type_application` is the right QUESTION and the wrong
        # CALLER here: it is asked with `structs_by_name` because its callers
        # need to know whether the WHOLE subscript is compile-time, which
        # depends on a base this unit has to have declared. An ELEMENT of
        # somebody else's parameter list does not: `List[Int]` is a type
        # application whoever asks, and `List` is in `type_constructor_kind`'s
        # table, so this asks the base name against the tables the same way the
        # bare-name arm below does rather than through a predicate whose answer
        # depends on state this call does not have.
        _bn = _base_name(node.obj)
        if (_bn is not None
                and (type_constructor_kind(_bn) is not None
                     or _bn in POINTER_TYPE_CTORS
                     or (structs_by_name and _bn in structs_by_name))):
            return "type"
    if isinstance(node, (F.IntLiteral, F.BoolLiteral, F.StringLiteral)):
        return "literal"
    if isinstance(node, F.BinaryOp):
        # Foldable arithmetic over literals: the only arithmetic on this path
        # that has a value without running anything, and the shape
        # `size_of[type, target]`-style code spells.
        if all(isinstance(p, (F.IntLiteral, F.BoolLiteral, F.StringLiteral))
               for p in (node.left, node.right)):
            return "literal"
    name = _base_name(node)
    if (name is not None
            and (type_constructor_kind(name) is not None
                 or name in POINTER_TYPE_CTORS
                 or (structs_by_name and name in structs_by_name))):
        return "type"
    # A `Self.X` attribute is a type PARAMETER reference — the stdlib spells
    # `_DequeIter[Self.ElementType, origin_of(self), False]` — and a parameter
    # reference is a type by construction, so it is claimed as one rather than
    # left to be reported as a name this image cannot resolve.
    if isinstance(node, F.MemberExpr) and _base_name(node.obj) == "Self":
        return "type"
    return "name"


def _comptime_param_element_sentence(e, structs_by_name=None) -> str:
    """Which bracket element has no word, as one sentence — or `''`.

    **The sentence is emitted only when it can name a culprit**, which is the
    condition that keeps it from being a guess. It fires when at least one
    element is a `'name'` AND at least one is positively classified, because
    only then is the contrast informative: a list of two types says the refusal
    is about the LIST and not about an element (which is the `size_of[type,
    target]` case the old sentence already served correctly, and it is still
    served). **When NO element resolves there is no culprit to name, and the
    sentence says the reader has two to resolve instead** — which is the honest
    answer and not a weaker one, because it is followed by the same
    `_UNRESOLVABLE_NAME_SHAPES` clause either way: a bare name has exactly two
    shapes here, and naming them is what tells the reader of
    `Span[StaticString, ImmStaticOrigin]` that the second one may be a `comptime`
    alias whose initializer is an MLIR attribute template in a module this build
    cannot fold — which is the whole of what can be said about it.

    **The clause is ONE string in both branches, not one per branch.** It used to
    live only in the mixed case, so the all-names case — which is what
    `std/sys/arg.mojo` gets, measured, because `StaticString` is in neither
    `type_constructor_kind` nor `POINTER_TYPE_CTORS` nor the struct table this
    unit compiled nor the 220 structs `formal/imports.py::imported_struct_defs`
    reaches from that file — named the two unresolved elements and stopped there.
    The reader was left to guess which of them was the interesting one.
    """
    els = list(getattr(getattr(e, "index", None), "elements", ()) or ())
    kinds = [_comptime_param_element_kind(x, structs_by_name) for x in els]
    if not kinds or "name" not in kinds:
        return ""
    if all(k == "name" for k in kinds):
        return (f" None of its {len(kinds)} element(s) names something this "
                f"image can resolve to a declaration "
                f"({', '.join(_spell(x) for x in els)}), so there is no word "
                f"to bind for any of them.{_UNRESOLVABLE_NAME_SHAPES}")
    shown, cls = [], []
    for i, (x, k) in enumerate(zip(els, kinds), 1):
        if k == "type":
            cls.append(f"element {i} `{_spell(x)}` is a type this image knows")
        elif k == "literal":
            cls.append(f"element {i} `{_spell(x)}` is a literal that folds")
    named = [f"element {i} `{_spell(x)}`" for i, (x, k)
             in enumerate(zip(els, kinds), 1) if k == "name"]
    return (f" Of its {len(kinds)} element(s): {'; '.join(cls)}; and "
            f"{' and '.join(named)} {'is a bare name' if len(named) == 1 else 'are bare names'}"
            f" this image cannot resolve to a declaration. That is where the "
            f"missing word is.{_UNRESOLVABLE_NAME_SHAPES}")


#: What a bare name in a comptime parameter list can BE, for a reader who has to
#: decide what to do about it. **One string, in both branches of
#: `_comptime_param_element_sentence`,** because a reader who is told "element 2
#: is unresolvable" and a reader who is told "both elements are unresolvable" are
#: in the same position: neither this call nor this backend can say which of the
#: two shapes the name has, and saying so is what stops the search.
#:
#: The second shape is the measured one and it is a fact about a module this
#: repository does not own: `std/sys/arg.mojo:51` spells
#: `Span[StaticString, ImmStaticOrigin]()`, where `ImmStaticOrigin` is a
#: `comptime` ALIAS in `std/origin/__init__.mojo` whose initializer is
#: `Origin[_mlir_attr[...]]()` — an MLIR attribute template, and that module does
#: not build here. So the word is missing because ANOTHER module's comptime
#: binding cannot be folded, not because this backend lacks a capability, and a
#: reader sent to look for a compiler limit would be looking in the wrong place.
_UNRESOLVABLE_NAME_SHAPES = (
    " A bare name has two shapes here, and this path cannot tell them apart: a "
    "TYPE this unit does not declare, or a `comptime` ALIAS whose initializer "
    "does not fold — measured on `std/sys/arg.mojo`'s "
    "`Span[StaticString, ImmStaticOrigin]`, whose second element is exactly the "
    "second shape, because `std/origin/__init__.mojo` binds it to "
    "`Origin[_mlir_attr[…]]()` and that module does not build. The word is "
    "missing because of a binding in another module, not because of a capability "
    "here."
)


def multi_index_refusal(kind: str, spelled: str, elements_note: str = "") -> str:
    """The refusal text for a multi-element subscript, identical on both paths.

    `spelled` is how the source wrote the construct, so the message points at
    something the reader can find (`size_of[type, target]`,
    `__mlir_attr[...]`, `a[i, j]`).

    `elements_note` is the per-element diagnosis, computed by
    `_comptime_param_element_sentence` and passed in rather than derived here —
    this function is handed a KIND and a SPELLING and has no node, and the one
    caller that does have a node is `multi_index_refusal_for`. It is empty for
    every kind but the comptime-parameter list, and empty means "nothing to add",
    which is the answer for the MLIR-template and tuple-index cases where every
    element's role is already covered by the sentence below."""
    if kind == MULTI_INDEX_MLIR_TEMPLATE:
        return (
            f"{spelled} assembles an MLIR attribute from a template of "
            "backtick-quoted literal fragments and compile-time "
            "sub-expressions: it is not a subscript, and there is no MLIR on "
            "this path for the template to become. Refused rather than "
            "materialized as a container, which would turn an attribute into "
            "a pointer to a frame blob and disagree with the compiler that "
            "does have MLIR."
        )
    if kind == MULTI_INDEX_COMPTIME_PARAMS:
        return (
            f"{spelled} is a compile-time explicit-parameter list on a "
            "generic, not a subscript: the brackets name types and comptime "
            "values, none of which is a runtime word. This path has no type "
            "or comptime parameter to bind, so what the call means depends "
            f"entirely on which parameters were passed.{elements_note} "
            "Refused rather than read as an index — a binding for "
            "`size_of[type, target]` would have to come from a target "
            "description this backend does not have, and a plausible constant "
            "is a fabricated answer."
        )
    return (
        f"{spelled} is a subscript whose index is a tuple. A value here is "
        "one 64-bit word and a list is a flat blob of words, so a tuple "
        "index has no representation on this path. It is one of two things: "
        "a lookup keyed by the tuple, which is lowered only when the base is "
        "a known dict and compares the key element-wise; or a "
        "two-dimensional index, which needs a row stride the source never "
        "states. Refused rather than computing a plausible flat index, and "
        "rather than using the tuple blob's own address as the index — that "
        "builds, runs, and returns an element nobody asked for."
    )


def multi_index_refusal_for(e, base_is_dict: bool, callee_defs: dict = None,
                            structs_by_name=None, own_template_structs=None):
    """The refusal text for `e`, or None when it is the lowered dict-key case.

    This is the ONE place either backend asks, so the two architectures
    cannot disagree about what a multi-element subscript means — the failure
    that was live at the time of writing: arm64 refused a computed tuple
    index while x86-64 used the tuple blob's own frame address as the element
    index, so `s[i, j]` segfaulted on one architecture and returned a
    different wrong answer on the other. `callee_defs` is the backend's
    `{name: FunctionDef}` table, consulted only to recognise a generic's
    explicit-parameter list; `structs_by_name` is the same table's TYPE half,
    for a bracket list on a type rather than on a function — see
    `multi_index_kind`, which is where both are decided, and
    `subscript_index_is_a_comptime_parameter_list` for why a base this image
    cannot classify falls through to the tuple-index refusal, which is still
    true of it. `own_template_structs` is the third half of the same fact, for
    this unit's own generic struct TEMPLATES, whose declarations
    `monomorph.without_template_bodies` has already removed from
    `structs_by_name` — see `subscript_index_is_a_comptime_parameter_list`.

    Called from the address computation, not from the read: that is the one
    place a read, a store and an augmented assignment all pass through, and the
    read-only check this replaces left `a[i, j] = v` unrefused.

    Callable UNCONDITIONALLY — the multi-element gate moved inside — because the
    MLIR answer does not depend on the arity (`is_mlir_template` keys on the
    base), and a caller that still guarded the call with `is_multi_index` would
    keep the single-element spelling `__mlir_type[x]` fabricated. A non-MLIR
    single index is not this function's business and returns None, exactly as
    before.

    `external_call["sym", RetType]` is asked HERE and not in `multi_index_kind`
    because it is the one multi-element construct whose answer is not a kind but
    a specific sentence: a well-formed one is LOWERED (it becomes a direct call
    to the C symbol, with the declared return type marshalling the result), and
    a malformed one is refused by `external_call_refusal` with the reason that
    shape is malformed. Routing it through the kind table would have made a
    refused template read as a two-dimensional index, which is the
    misdiagnosis §6.2 of bugs/FORMAL_known_limits.md is about.

    The module's OWN `external_call` declaration wins over the language's
    template, which is why `callee_defs` is consulted first: a module that
    declares `def external_call[a, b](…)` has said what the name means in that
    module, and its explicit-parameter list is then the same comptime-params
    case as any other generic."""
    why = mlir_template_refusal(e)
    if why is not None:
        return why
    if not is_multi_index(getattr(e, "index", None)):
        return None
    callee_defs = callee_defs or {}
    if (callee_defs.get(_base_name(e.obj)) is None
            and is_external_call_template(e)):
        _symbol, _kind, xc_why = external_call_spec(e)
        if xc_why is None:
            return None
        return external_call_refusal(external_call_spelling(e), xc_why)
    kind = multi_index_kind(e, base_is_dict=base_is_dict,
                            generic_callee=(
                                (callee_defs or {}).get(_base_name(e.obj))),
                            structs_by_name=structs_by_name,
                            callee_defs=callee_defs,
                            own_template_structs=own_template_structs)
    if kind is None:
        return None
    # The per-element diagnosis, and ONLY for the kind it is about: which
    # bracket element has no word is a question about a compile-time parameter
    # list, and for the MLIR-template and tuple-index kinds every element's role
    # is already stated by the sentence they share.
    note = (_comptime_param_element_sentence(e, structs_by_name)
            if kind == MULTI_INDEX_COMPTIME_PARAMS else "")
    return multi_index_refusal(kind, multi_index_spelling(e), note)




# ── `external_call["sym", RetType](args…)` ─────────────────────────────────
#
# The construct behind the largest single family in the sweep residue (55 stdlib
# files, one terminal module: `std/os/env.mojo`), and the one multi-element
# subscript in the whole corpus that is NOT a generic's explicit-parameter list.
# The tuple-index refusal above is true of the SHAPE and wrong about the
# MECHANISM, which §6.2 of bugs/FORMAL_known_limits.md is the audit of: the base
# is a function-like template, the first bracket element is the SYMBOL to call
# and the second is the declared return type. Neither is a coordinate, and
# `external_call` is not a dict.
#
# So it is lowered, and what it lowers to is the extern call both backends
# already emit — the arguments into the ABI's argument registers, a branch to
# the C symbol — plus the ONE thing an extern call has no way to know and this
# construct states outright: the declared return type.
#
# It is a marshalling instruction here, not documentation.  Both ABIs put the
# low `bits` of a narrow integer return in the return register and say nothing
# about the rest, and on both of these ISAs a narrow register WRITE zero-
# extends, so what actually arrives is the low `bits` ZERO-extended.  The
# declared type is usually SIGNED — `Int32` and `c_int` cover every
# `status`-shaped call in the corpus — and the source means the SIGN-extended
# value: `zero_extend(0xFFFFFFFF)` is 4294967295 and `sign_extend(0xFFFFFFFF)`
# is -1.  So without the extension a program can read a plausible positive
# number where the source says a negative one.  The reference lowering
# (`mojo/backend_gimple/emit_exprs.py::_lower_external_call`) gets this for
# free by emitting `extern int32_t setenv();` and letting C's typed assignment
# do the conversion; a machine-code backend has to be told, and the source
# already said.
#
# MEASURED, so the claim is not stronger than it is: every libSystem symbol
# reachable from this corpus (`strcmp`, `atoi`, `memcmp`, `strcasecmp`) already
# hands back a sign-extended 64-bit word on this host, so the extension is a
# no-op instruction for all of them TODAY.  It is kept anyway, and the reason is
# the one sentence above: a value model may not take its correctness from one
# libc's internal choice about a register the ABI leaves unspecified, and the
# answer to match is the reference lowering's.

# The one name the template is spelled. A frozenset of one, so a caller reads
# it as "the base name that means this" rather than as a private string; see
# `multi_index_kind` for why a module that DECLARES its own `external_call`
# generic still means that generic instead (the callee table is consulted
# first, and it is the module's own declaration that is the stronger fact).
EXTERNAL_CALL_NAMES = frozenset({"external_call"})

# What a declared return type says about the return register.
#   "void" — the callee returns nothing; the register is meaningless and the
#            source discards it.  Also the answer for the one-element bracket
#            `external_call["sym"]`, because that is what the reference lowering
#            emits for it (`ret_ct = 'void'` when the bracket has no second
#            element), and matching the compiler that does have the C type
#            system matters more than being stricter than it.
#   "word" — the whole 64-bit register IS the answer.  Every pointer, and every
#            64-bit integer, on both targets: pointers are addresses and the
#            integer types are the word this path's values already are.
#   ("int", (bits, signed)) — the low `bits` of the register are the answer
#            and the backend sign/zero-extends to it.  `Int32` (env.mojo's
#            `setenv`), `c_int` (its `unsetenv`), `UInt8` (a C `_Bool`).
EXTERN_RETURN_VOID = "void"
EXTERN_RETURN_WORD = "word"

# `(bits, signed)` for the declared integer return types a C function has.
#
# Deliberately NOT `POINTEE_WIDTHS`, which is a different question with a
# deceptively similar answer: that table says how many bytes a LOAD of a
# pointee of this type reads, and it is C-flavoured, so its `Int` is four bytes
# (C's `int`) where a DECLARED `Int` is Mojo's `Int64`. Reading a declared
# return type through it would truncate a 64-bit return to 32 on the strength of
# a table written about something else. Two tables, two questions, both named
# for what they answer.
EXTERN_RETURN_INTS = {
    # Mojo's own integer types. `Int`/`UInt` are 64-bit HERE, which is the one
    # entry the two tables disagree about and the reason they are separate.
    "Int": (64, True), "int": (64, True),
    "Int8": (8, True), "Int16": (16, True),
    "Int32": (32, True), "Int64": (64, True),
    "UInt": (64, False),
    "UInt8": (8, False), "UInt16": (16, False),
    "UInt32": (32, False), "UInt64": (64, False),
    # A C `_Bool`/`bool` is one byte, and a program that reads it as a word
    # wants it zero-extended — an uninitialised top half would make every
    # comparison of it a coin flip, which is the whole hazard this section is
    # about.
    "Bool": (8, False),
    # The C aliases `std/ffi/__init__.mojo` declares. Read HERE BY NAME,
    # because a declared return type reaches this as a type EXPRESSION in the
    # AST: `c_int` is an `IdentExpr` naming a module-level `comptime` binding,
    # and this path does not resolve a module-level comptime binding to its
    # target (that is the `std/sys/info.mojo` capability, and a separate one).
    # The widths are the ones `std/ffi` itself states — `comptime c_int =
    # Int32`, `c_ssize_t = Int`, `c_size_t = UInt`, `c_pid_t = Int` — so this
    # table and the source cannot drift into disagreeing about what a C `int`
    # is. `c_float`/`c_double` are deliberately absent: this path has no float
    # kind (`POINTEES_REFUSED` says why, for the same reason), and a `double`
    # return read as a word would be a number nobody wrote.
    "c_char": (8, True), "c_uchar": (8, False),
    "c_short": (16, True), "c_ushort": (16, False),
    "c_int": (32, True), "c_uint": (32, False),
    "c_long": (64, True), "c_ulong": (64, False),
    "c_long_long": (64, True), "c_ulong_long": (64, False),
    "c_ssize_t": (64, True), "c_size_t": (64, False),
    "c_pid_t": (64, True),
}


def external_call_return_kind(text):
    """How the declared return type marshals the return register, or None.

    `text` is a declared type rendered by `type_expr_text` — the same string
    shape a `VarDecl.type_ann` arrives in, which is why that one function
    renders the AST node into it rather than this module growing a second
    spelling.

    None means "this path cannot say", and the caller must refuse: a return
    type this module has never heard of is a value whose width was never
    established, and a call whose result is an unestablished number is the
    silent-wrong-answer shape the whole value model is built to refuse.  Every
    refusal below is a real thing a declared return can be and none of them
    is answerable by widening the register:

      * a pointer — `Pointer`, `UnsafePointer`, `_CPointer[UInt8, …]`,
        `_CString`, `FILE_ptr` — is an address, so `"word"`, and it needs no
        pointee: the return VALUE is the address the C function handed back,
        and `env.mojo`'s `if not ptr:` reads exactly that.
      * a string type is a bare `char *` here (`STRING_TYPE_CTORS`), so also
        `"word"` — `getenv` declares a `_CPointer[UInt8, …]` and the source
        then builds a `String` from it.
      * `NoneType` is `void`: the C prototype has no return, so there is
        nothing in the register to extend (`KGEN_CompilerRT_GetArgV` and the
        rest of the runtime's void entry points).

    **What "at a C boundary" is doing in that list, and why it is not a claim
    about `Optional`.** `bugs/FORMAL_stdlib_optional_needs_a_representation.md`
    measures `Optional[Pointer[T]]` as one word whose payload is the address and
    whose TAG lives a second frame away, so `if not ptr:` cannot be answered from
    the word: `Some(null)` and `None` are two Mojo values of one word. That is a
    fact about an `Optional` a MOJO function built, and it is why `Optional` is
    not in `POINTER_TYPE_CTORS` and must not be added to it.

    A C function has no such thing. `char *getenv(const char *)` returns one
    word, and by the C ABI a null pointer IS the "absent" answer — there is no
    second register and no tag, so a caller cannot distinguish them and neither
    can this. So for a declared return type that is one of the NULLABLE POINTER
    ALIASES (`OptionalPointer`, `OpaquePointer` — both already in
    `POINTER_TYPE_CTORS`, which is what answers them), the register holds that
    word and nothing else, and refusing it says "this path cannot tell how wide a
    pointer is", which is false. The OTHER question about those two names — that
    a `.value()` on one is an unwrap and not a load — is asked by
    `NULLABLE_POINTER_UNWRAP_ALIASES` and by nothing here.

    Measured: `std/os/env.mojo`'s `getenv` declares
    `external_call["getenv", OptionalPointer[UInt8, ImmUntrackedOrigin]]` and was
    refused here — "`this path has no value of that kind to put in the return
    register`" — which took `std/os/env.mojo` and the three `std/random` files
    behind it (`__init__`, `_rng`, `random`) out of the build. Whether `ptr` can
    then be READ (`if not ptr:`, `ptr.value()`) is a separate question with its
    own answer, and it is the one that document is about.
    """
    if not text:
        return None
    base = annotation_base_name(text)
    if base is None:
        return None
    if base == "NoneType":
        return EXTERN_RETURN_VOID
    if base in POINTER_TYPE_CTORS or base in STRING_TYPE_CTORS:
        return EXTERN_RETURN_WORD
    # A name this path does not know is refused, NOT passed through as a word:
    # a `SIMD[dtype, 4]` or a `Scalar[dtype]` return is n words, and dropping
    # n-1 of them is the "returns a value nobody asked for" outcome the
    # tuple-index refusal above exists to avoid.
    info = EXTERN_RETURN_INTS.get(base)
    if info is not None:
        return info
    return None




# ── The same ABI rule for a BARE C call, which has no declared type to read it from
#
# `external_call_return_kind` above answers "what does the DECLARED return type
# say about the return register", and the emitters' `_emit_extern_return` turns
# that into the conversion.  A BARE call — `return mkdir(p, mode)`, which is how
# every `formal/hostmods/os/_syscalls.mojo` wrapper reaches libSystem — has no
# declaration, so the answer was `None`, so the register was handed on exactly as
# the callee left it.  And the C ABI does not promise that is usable: AAPCS64
# puts the low 32 bits of a narrow integer return in X0 and leaves the rest
# UNSPECIFIED, so whether a `-1` arrives as `0xFFFFFFFF_FFFFFFFF` or as
# `0x00000000_FFFFFFFF` is a property of the host library's syscall sequence and
# not of anything the source says.  Measured on both architectures, 2026-10-03:
#
#     printf("%d", mkstemps(b, 0) == -1)   ->  0     (the host returned -1)
#     printf("%d", mkstemps(b, 0) == 4294967295)  ->  1
#
# while `access(p, 2) == -1`, the identical signature, answers 1 — so the
# exposure is per CALL SITE, and no rule about which symbols "need" fixing
# survives a libsystem update.  The answer is the same one the comment above
# `EXTERN_RETURN_INTS` already gives for a declared return: a value model may
# not take its correctness from one libc's internal choice about a register the
# ABI leaves unspecified, so the conversion is emitted from the C PROTOTYPE
# instead.
#
# WHY A TABLE OF PROTOTYPES RATHER THAN "SIGN-EXTEND EVERY BARE CALL", which is
# the smaller change and is wrong: a `size_t`, an `off_t` or a `uint64_t` return
# has bit 31 set in ordinary use, and sign-extending it fabricates a negative
# number.  `formal/hostmods/time.mojo`'s `time_ns()` is
# `clock_gettime_nsec_np(0)` — 1.7e18 nanoseconds, bit 31 long since set — and a
# blanket `sxtw` there would make `time.time_ns()` negative on every run.  A
# prototype table has no such case: it says what each callee RETURNS, which is
# a stable property of the C library's header, and the conversion it asks for is
# idempotent — sign-extending an already sign-extended `-1` is a no-op, which is
# why the one instruction covers both of the arrival conventions above instead
# of only the broken one.
#
# The `VOID` and `WORD` entries are no-ops in the emitter and are here anyway so
# the table is TOTAL over the corpus: `bare_c_return_kind` can then answer for
# every bare C call this tree makes, and `test_formal_libc_symbol.py`'s
# `every_bare_c_call_in_the_hostmods_has_a_prototype` can demand an entry for
# each one, so a host module that starts calling something new cannot arrive
# unnormalised and silently.  A 64-bit integer is spelled `WORD` because it is
# the same instruction — none — and two spellings of one answer is two things to
# keep in step.
#
# Every width here was read out of this SDK's headers rather than from memory,
# with `clang -Xclang -ast-dump` over a probe that references each symbol.
BARE_C_RETURN_KINDS = {


    # ── `int`: the low 32 bits are the answer, sign-extended. The whole
    # failure-check vocabulary of the C library is here — every one of these
    # returns 0 or -1, and `-1` compared as a 64-bit word is the bug.
    "access": (32, True),
    "atoi": (32, True),
    "chdir": (32, True),
    "chmod": (32, True),
    "close": (32, True),
    "closedir": (32, True),
    "fcntl": (32, True),
    "fclose": (32, True),
    "fflush": (32, True),
    "flock": (32, True),
    "getpid": (32, True),
    "kill": (32, True),
    "memcmp": (32, True),
    "mkdir": (32, True),
    "mkstemps": (32, True),       # the row that measured the bug
    "open": (32, True),
    "printf": (32, True),
    "remove": (32, True),
    "rename": (32, True),
    "rmdir": (32, True),
    "setenv": (32, True),
    "snprintf": (32, True),
    "stat": (32, True),
    "strcmp": (32, True),
    "strcasecmp": (32, True),
    "strncmp": (32, True),
    "sysctlbyname": (32, True),
    "truncate": (32, True),
    "uname": (32, True),
    "unlink": (32, True),
    "unsetenv": (32, True),
    "usleep": (32, True),
    "utimes": (32, True),
    "lstat": (32, True),
    # The row the 2026-10-05 corpus census FOUND after this table's totality was
    # first pinned, so the claim that every real libc bare callee had a row had
    # already gone stale. It is the one the bug doc quotes: `strcasecmp("a","b")`
    # built, ran and answered 4294967295 where C answers -1, and `a < 0`
    # answered `no`, on both architectures and byte-identical.
    "strcasecmp": (32, True),



    # ── 64-bit integers and sizes: the whole register is the answer. The
    # `clock_gettime_nsec_np` row is the one that says why this group exists.
    "clock_gettime_nsec_np": EXTERN_RETURN_WORD,
    "fread": EXTERN_RETURN_WORD,
    "fwrite": EXTERN_RETURN_WORD,
    "lseek": EXTERN_RETURN_WORD,
    "read": EXTERN_RETURN_WORD,
    "strcspn": EXTERN_RETURN_WORD,
    "strlen": EXTERN_RETURN_WORD,
    "strspn": EXTERN_RETURN_WORD,
    "write": EXTERN_RETURN_WORD,



    # ── pointers: an address, which is below `0x0000_8000_0000_0000` on every
    # user-space target this backend emits, so a NULL compares as 0 either way.
    "dlopen": EXTERN_RETURN_WORD,
    "dlsym": EXTERN_RETURN_WORD,
    "fopen": EXTERN_RETURN_WORD,
    "getcwd": EXTERN_RETURN_WORD,
    "getenv": EXTERN_RETURN_WORD,
    "getpwnam": EXTERN_RETURN_WORD,
    "malloc": EXTERN_RETURN_WORD,
    "memcpy": EXTERN_RETURN_WORD,
    "memmove": EXTERN_RETURN_WORD,
    "memset": EXTERN_RETURN_WORD,
    "mkdtemp": EXTERN_RETURN_WORD,
    "opendir": EXTERN_RETURN_WORD,
    "readdir": EXTERN_RETURN_WORD,
    "realloc": EXTERN_RETURN_WORD,
    "realpath": EXTERN_RETURN_WORD,
    "strcat": EXTERN_RETURN_WORD,
    "strchr": EXTERN_RETURN_WORD,
    "strsignal": EXTERN_RETURN_WORD,
    # …and the three MORE the 2026-10-05 corpus census found without rows, the
    # same walk that found `strcasecmp`: `atof`/`atol` are reached by
    # `stdlib/std/collections/string/string_span.mojo` and
    # `stdlib/std/python/_cpython.mojo`, `index` (libc's own spelling of
    # `strchr`) by `stdlib/std/builtin/range.mojo` and
    # `stdlib/std/collections/array.mojo`. Their widths were read out of this
    # SDK's headers with `clang -Xclang -ast-dump`, the same way as every row
    # above — and they are the reason the three are here rather than guessed:
    #
    #     atof   double (const char *)      atof is a DOUBLE, so the whole
    #     atol   long (const char *)        register, and `atol` is a 64-bit
    #     index  char *(const char *, int)  `long` under LP64 on both targets.
    #
    # A `(32, True)` row on any of the three would fabricate a negative number,
    # which is the argument `time_ns` makes above and the reason these widths are
    # measured rather than assumed — `strtol` and `atoll` are the same two
    # conversions at `long`/`long long` and would be the same wrong answer if
    # they were reached bare without a row.
    "atof": EXTERN_RETURN_WORD,
    "atol": EXTERN_RETURN_WORD,
    "index": EXTERN_RETURN_WORD,
    # `getpwnam` and `strsignal` are the two `struct passwd *` / `char *`
    # returns `formal/hostmods/os/_syscalls.mojo` reads, and both are here for
    # the reason the whole pointer group is: an address is below
    # `0x0000_8000_0000_0000` on every user-space target this backend emits, so
    # a NULL compares as 0 either way and the conversion has nothing to do. The
    # question they raise is the OPPOSITE one from `getpid`/`kill` above — both
    # of those are `int`, so BOTH need the sign-extension — and all four are
    # asked of the same census, which is what makes the pair worth stating
    # together.
    "CC_MD5": EXTERN_RETURN_WORD,
    "CC_SHA1": EXTERN_RETURN_WORD,
    "CC_SHA224": EXTERN_RETURN_WORD,
    "CC_SHA256": EXTERN_RETURN_WORD,
    "CC_SHA384": EXTERN_RETURN_WORD,
    "CC_SHA512": EXTERN_RETURN_WORD,

    # ── nothing comes back.
    "arc4random_buf": EXTERN_RETURN_VOID,
    "exit": EXTERN_RETURN_VOID,
    "free": EXTERN_RETURN_VOID,
    "rewinddir": EXTERN_RETURN_VOID,
}


def _libsystem_handle():
    """A dlopen-able handle on the C library this image's load command names.

    `None` until the first attempt settles, then either a handle or `False`
    for "this host will not let us ask". A caller that races the first attempt
    does not read the in-between state: it blocks on `_LIBSYSTEM_LOAD_LOCK`
    until the attempt has settled, and then reads the settled answer — the
    in-between used to be a `False` marker, and a second thread read it as the
    answer instead of the state. Deliberately NOT `ctypes.CDLL(None)`: the global
    namespace contains everything the *building* process has loaded, so it
    answers questions about the compiler rather than about the target.
    Measured on this machine, same symbol, two handles:

        CDLL('/usr/lib/libSystem.B.dylib')   sqlite3_open -> False   correct
        CDLL(None)                           sqlite3_open -> True    WRONG

    because this python has libsqlite3 in its own global namespace. A build-time
    audit that inherits that would wave through exactly the symbols it exists to
    catch. `tools/formal_sweep.py` reached the same conclusion about its own
    earlier probe, and for the same reason, its own comment is explicit that the
    global namespace "is a false PASS".
    """
    global _LIBSYSTEM_HANDLE
    if _LIBSYSTEM_HANDLE is None:
        with _LIBSYSTEM_LOAD_LOCK:
            # Re-check under the lock: a caller that raced the first attempt
            # is BLOCKED on this lock until it settles, and then reads the
            # settled answer. Before this, the in-flight marker was `False`,
            # and a second thread entering during the load read that marker as
            # "not a C library symbol" and memoised the answer for the whole
            # process — `snprintf` and `strtod` dropped out of the provided
            # set, and every later build in it refused with "the image would
            # bind 2 symbol(s) that nothing provides".
            if _LIBSYSTEM_HANDLE is None:
                try:
                    import ctypes
                    import platform
                    if platform.system() == "Darwin":
                        from formal.macho_linker import LIBSYSTEM_PATH
                        name = LIBSYSTEM_PATH.decode().rstrip("\0")
                    else:
                        from formal.elf import DEFAULT_LIBC
                        name = DEFAULT_LIBC
                    _LIBSYSTEM_HANDLE = ctypes.CDLL(name)
                except Exception:
                    _LIBSYSTEM_HANDLE = False
    return _LIBSYSTEM_HANDLE


# The first attempt is the only thread that may be mid-load: it holds this
# lock, and a caller racing it blocks on the lock instead of reading the
# in-between state (double-checked locking, sound here because the GIL orders
# the fully-constructed handle before any other thread can read the global).
_LIBSYSTEM_LOAD_LOCK = threading.Lock()
# `None` until the first attempt settles, then a handle or `False` for "this
# host will not let us ask". The in-flight state is no longer a value a
# concurrent caller can observe: it is the lock, not a word in the global.
_LIBSYSTEM_HANDLE = None

# The 19 names this function used to hardcode, kept ONLY as the fallback for a
# host that will not let us dlopen its C library. They are a guess at names
# rather than a check of anything, which is the whole reason the real table
# exists; on such a host this is no worse than the behaviour being replaced.
_LIBSYSTEM_LEGACY = frozenset((
    "printf", "puts", "putchar", "malloc", "calloc", "realloc", "free",
    "memcpy", "memset", "strlen", "strcmp", "strncmp", "abort", "exit",
    "atoi", "qsort", "fmod", "pow", "sqrt",
))

# memo: bare symbol -> bool
_LIBSYSTEM_MEMO = {}


def _is_libsystem(sym: str) -> bool:
    """True for a symbol the C library this image links actually provides.

    The externs a library legitimately sends outward are the C library's own
    (`printf`, `malloc`, …), and those are declared by the libSystem load
    command the image already carries. Everything else has to come from a
    dependency's export table.

    This used to be a 19-name literal, which was a guess at names rather than a
    check of anything, and it was wrong in the direction that hides defects: a
    formal program calling `stat`, `clock_gettime`, `regcomp` or `arc4random_buf`
    — all of which libSystem genuinely provides, and all of which are the whole
    reason a module like `os` or `re` is in the *modelled* half of
    `formal/imports.py`'s host split — was reported as binding a symbol nothing
    provides. Now the answer comes from dlsym against the real library.

    The name asked about is `model.libc_source_name`'s, not the symbol's own
    spelling, and the difference is a whole architecture's worth: a
    `readdir$INODE64` in the symbol list is the 64-bit-inode `readdir(3)` (see
    `model.target_libc_symbol`), and the dlsym here runs in THIS python3, so it
    can only answer for the host — where that spelling may not exist at all. On
    an arm64 host asking about `readdir$INODE64` would report an x86-64 image's
    correct binding as a symbol nothing provides, which is a build refused over
    a name that is right.

    Memoised per symbol: this runs once per extern per build, and a dlsym per
    extern would be a needless syscall storm in a large program.
    """
    bare = libc_source_name(sym) if isinstance(sym, str) else sym
    if not bare:
        return False
    hit = _LIBSYSTEM_MEMO.get(bare)
    if hit is not None:
        return hit
    handle = _libsystem_handle()
    if handle is False:
        answer = bare in _LIBSYSTEM_LEGACY
    else:
        try:
            answer = hasattr(handle, bare)
        except Exception:
            answer = bare in _LIBSYSTEM_LEGACY
    _LIBSYSTEM_MEMO[bare] = answer
    return answer


# Bare callees this tree spells that are NOT C library entry points (the
# test that censuses them imports this set). An exact list rather than a
# filter, so a new name has to be classified rather than quietly skipped.
NON_C_BARE_CALLEES = {
    "admitted": "`@admitted` is a contract decorator "
                "(formal/admitted.py::ADMITTED_DECORATOR), not a call",
    "basename": "`os.path`'s own, reached by `glob.mojo` with no import "
                "statement — it binds `os_path_basename_<hash>` from the "
                "os.path dylib, measured in the `binding` group",
    "dirname": "`os.path`'s own, the same shape and the same measurement as "
               "`basename`",
    "str_copy": "`os._syscalls`' own byte copy, called from os/__init__.mojo "
                "the same way",
}

def bare_c_callee_is_project_function(callee: str, by_name: dict,
                                      by_module: dict, forwarded: dict,
                                      aliases: dict, dylib_syms: dict) -> bool:
    """True when a bare callee's return is a MOJO value, whatever it is spelled.

    Two ways, and they are the two halves of `bare_c_return_kind`'s `None`:

      * the name is one a linked Mojo library PUBLISHES — a symbol on this
        image's link line whose return is a formal value, whose width is this
        path's own 64-bit word whatever the function is called;
      * the name arrives through an import ALIAS, which is how
        `from m import f as g` binds and is the same fact with a different
        spelling on the source side.

    Split out from `bare_c_return_kind` because `refuse_unprototyped_bare_call`
    below asks the same question for the OPPOSITE reason and must reach the same
    answer: the export exception is what stops a call into another host module
    from being refused as an unprototyped C call, and a second copy of the
    resolution order in the refusal is a second chance for the two to disagree
    about `read`, which is libc's and this tree's own at the same time.

    **Which library answered is asked of `dylib_callee_export`** — the ONE
    resolution, in `dylib_extern_symbol`'s order — rather than decided here,
    because a caller that asked in a different order could normalise a call to
    somebody's Mojo function as though libc had declared it.
    """
    return (callee in dylib_syms
            or dylib_callee_export(by_name, by_module, forwarded, aliases,
                                   callee) is not None)


def bare_c_return_kind(callee: str, by_name: dict, by_module: dict,
                       forwarded: dict, aliases: dict, dylib_syms: dict):
    """What a BARE call's C prototype says about the return register, or None.

    `None` means two different things and both are the same answer to the
    question the emitters ask ("emit a conversion here?"): the callee is a
    function a linked Mojo library PUBLISHES — so its return is a Mojo value
    whose width is this path's own 64-bit word whatever the symbol is spelled —
    or the callee is a C symbol with no entry above.

    **The second half of that `None` used to be silently WRONG, and the split
    above is what makes the difference visible.** A C callee with no row means
    its return WIDTH is not established anywhere, so the register is handed on as
    it arrived — and for a return narrower than eight bytes what arrives is
    unspecified by the ABI (AAPCS64 §6.9, SysV AMD64 §3.2.3), which on both of
    this path's targets means zero-extended. Measured, both architectures,
    byte-identical: `strcasecmp("a","b")` answers 4294967295 where C answers
    -1, `a < 0` answers `no`, `a == -1` answers `no`. So a `None` from this
    function is no longer allowed to be the whole answer for a name the C
    library defines — `refuse_unprototyped_bare_call` is asked beside it and
    names the symbol instead of guessing its prototype.

    The export half is not optional and it is the whole reason the decision is
    not one line at the `BL`.  A name is extern exactly when this unit does not
    compile it, and a call into another host module is extern too, so `read`,
    `stat`, `remove`, `walk` and `isdir` all reach this line whether the callee
    is libc's `read` or this project's own.  Which library answered is asked of
    `dylib_callee_export` — the ONE resolution, in `dylib_extern_symbol`'s order
    — rather than here, because a caller that asked in a different order could
    normalise a call to somebody's Mojo function as though libc had declared it."""
    if bare_c_callee_is_project_function(callee, by_name, by_module, forwarded,
                                         aliases, dylib_syms):
        return None
    kind = BARE_C_RETURN_KINDS.get(callee)
    if kind is not None:
        return kind
    if callee in NON_C_BARE_CALLEES:
        return None
    if _is_libsystem(callee):
        raise CodegenError(
            f"bare call to `{callee}`: it is a symbol the linked C library "
            f"provides, but it has no row in BARE_C_RETURN_KINDS, so its "
            f"return register would arrive UNSIGNED and be handed on as a "
            f"word — a C `int` return that was never sign-extended, which is "
            f"a silent wrong value (and a wrong `a < 0`) on both "
            f"architectures. Add a row naming its C prototype "
            f"((32, True) for a C `int` return, EXTERN_RETURN_WORD for a "
            f"64-bit integer/size/pointer return, EXTERN_RETURN_VOID for "
            f"nothing), or, if this name is this project's own, spell the "
            f"import so the dylib export test resolves it rather than "
            f"reaching this line bare.")
    return None


def refuse_unprototyped_bare_c_call(callee: str, by_name: dict, by_module: dict,
                                    forwarded: dict, aliases: dict,
                                    dylib_syms: dict) -> str:
    """The sentence refusing a bare C call whose return width is unestablished,
    or `""` when there is nothing to refuse.

    ## The rule, and why it is a refusal rather than a widening

    A bare callee with no `BARE_C_RETURN_KINDS` row has no PROTOTYPE on this
    path, so the width of what comes back in the return register is not
    established by anything. That is not the same as "it is a word": AAPCS64 §6.9
    and SysV AMD64 §3.2.3 both say a value narrower than eight bytes is returned
    in the least significant bits and the remaining bits are **unspecified**, so
    the model's value for such a register is a free variable rather than a
    number the source determined. Measured, both architectures and byte-identical
    before this rule existed:

        var a = strcasecmp("a", "b")     # libc's `int`
        printf("%lld", a)   ->  4294967295      C: -1
        printf("%d", a < 0) ->  0               C: 1
        printf("%d", a == -1) -> 0              C: 1

    So the defect is not a conversion that was got wrong; it is that there was no
    answer to give and the build emitted a program anyway. Every operation on
    that word — a comparison most of all — is a silent wrong boolean, and it is
    invisible to any test whose subject is an arithmetic expression.

    ## Why the scope is "a symbol the target's C library DEFINES"

    Three reasons, and they are not interchangeable:

      * **a linked Mojo library's export** is excluded by the shared
        `bare_c_callee_is_project_function`, because its return IS a formal
        value. This is the row that matters in practice: `basename` and
        `dirname` are real libSystem symbols (`ctypes`/`dlsym` finds both, and
        the backward totality check in `test_formal_libc_symbol.py` would NOT
        have caught a mistake about either) yet `formal/hostmods/glob.mojo`
        reaches this project's own `os.path` functions of those names, so a rule
        keyed on the spelling alone would refuse a call that compiles and runs
        today.
      * **a name the C library does not define** is left alone, because the
        build's own bind audit already reports it — as a symbol nothing on the
        link line provides, which is a more accurate sentence than this one and
        costs the caller no rewrite. Refusing here would replace a linker
        message with a compiler one and lose the linker's.
      * **a callee reached through a VALUE** (`callee_is_a_bound_value`) never
        reaches this function at all: `is_extern` is False for it, so this is
        not in its scope.

    ## Why not widen instead

    "Sign-extend every bare call" is the one-line change and it is wrong in the
    direction that fabricates numbers rather than losing them: a `size_t`, an
    `off_t` or a `uint64_t` return has bit 31 set in ordinary use, and
    `formal/hostmods/time.mojo`'s `time_ns()` — 1.7e18 nanoseconds — would come
    back negative on every run. There is no conversion that is safe without the
    prototype, so the build says so.

    ## Why not derive the prototype

    The headers are on disk and could be scanned, and that is not what this does:
    the answer would then come from `clang`'s interpretation of a header rather
    than from anything measured, and a `#define`, an `_Noreturn` attribute or a
    target-conditional declaration is enough to make it wrong in the direction
    that is invisible. A refusal a reader can act on is worth more here than a
    guess that is right until the SDK moves, and the fix for a name this refuses
    is one line in a table whose every other entry was read out of the same
    headers.

    `""` — not None — for "no refusal", because every caller in this tree asks
    the `*_refusal` family for a sentence and tests it for emptiness.
    """
    if callee in BARE_C_RETURN_KINDS:
        return ""
    if bare_c_callee_is_project_function(callee, by_name, by_module, forwarded,
                                         aliases, dylib_syms):
        return ""
    if not libc_defines(callee):
        return ""
    return (
        f"'{callee}' is a C library function and this build has no prototype "
        f"for what it returns, so the value coming back in the return register "
        f"has no established width. The C ABIs both say a value narrower than "
        f"eight bytes is returned in the least significant bits and the rest is "
        f"UNSPECIFIED (AAPCS64 6.9, SysV AMD64 3.2.3), and on this target the "
        f"unspecified half arrives zero-extended — so the word this image holds "
        f"is not the number libc returned: `strcasecmp(\"a\", \"b\")` builds, "
        f"runs and answers 4294967295 where C answers -1, and `a < 0` answers "
        f"no. Give the call a declared return type with "
        f"`external_call[\"{callee}\", T](...)`, or add a "
        f"`BARE_C_RETURN_KINDS` row in formal/model.py for it — `(32, True)` "
        f"for a C `int`, `EXTERN_RETURN_WORD` for a pointer or a 64-bit "
        f"integer, `EXTERN_RETURN_VOID` for nothing — read out of the SDK's "
        f"headers rather than guessed at, because the two are different "
        f"instructions and guessing wrong fabricates a number instead of "
        f"failing")


def is_external_call_template(e) -> bool:
    """True when `e` is `external_call[...]` — the template, whatever it is
    applied to.

    The BASE NAME alone, so `external_call["sym"]`, `external_call["sym", T]`
    and `external_call["sym", T, P, Q]` are all recognised and a malformed one
    is refused by `external_call_spec` with a message about the template rather
    than falling through to the tuple-index text, which would name a data
    subscript that is not there.
    """
    return (isinstance(e, F.SubscriptExpr)
            and _base_name(e.obj) in EXTERNAL_CALL_NAMES)


def external_call_spec(e):
    """`(symbol, return_kind, why)` for an `external_call[...]` template, or
    None when `e` is not that construct at all.

    `None` is "not this construct" and every caller asks `is_external_call_
    template` first, so the two cannot disagree about what this function
    claims. When `e` IS the construct the answer is always a 3-tuple:
    `symbol` is the C symbol to branch to, `return_kind` is what
    `external_call_return_kind` says, and `why` is None or the CLAUSE saying
    which part is not lowerable.

    `why` is a clause and not a whole sentence because `external_call_refusal`
    prefixes the construct's spelling, and there is one place that decides how
    a source construct is written in a diagnostic (`multi_index_spelling`) — a
    second spelling here would be two answers to "what did the file say" and
    they would drift the first time a new shape needed a different rendering.

    The refusals here are about the TEMPLATE, never about the data index:
      * the first element is not a string literal.  `external_call[name,
        T](…)` with a name bound by a `comptime` parameter does occur in the
        stdlib (`std/sys/info.mojo`), and a symbol that is not a literal is not
        knowable at the point the call is lowered — the branch's target would
        have to come from a register, which is how an image gets a call to
        wherever that register happened to point.
      * a bare `external_call` with no bracket at all, which is a name nobody
        declared, and belongs to the name-placement rules rather than here.
      * more than two elements: the third is a PARAMETER type list the C
        prototype already states, and this path has no parameter types to
        marshal with, so taking the first two and ignoring the rest would be a
        call that does not say what the source says.
    """
    if not is_external_call_template(e):
        return None
    if getattr(e, "attrs", None):
        return (None, None,
                "applies the external_call template with keyword attributes. "
                "The template's bracket is the symbol and the declared return "
                "type, and nothing else; there is no keyword form of it to "
                "honour here, and ignoring the attributes would call a symbol "
                "the source did not spell")
    items = list(e.index.elements) if isinstance(e.index, F.TupleExpr) else [e.index]
    if len(items) > 2:
        return (None, None,
                f"applies the external_call template with {len(items)} "
                f"arguments. The template takes the symbol and the declared "
                f"return type; a third element would be a C parameter type "
                f"list, which this path has no way to marshal with — the C "
                f"prototype on the link line states it, and taking the first "
                f"two and dropping the rest would build a call that is not the "
                f"one the source wrote")
    if len(items) < 2:
        # No declared return type is the reference lowering's `void`
        # (`ret_ct = 'void'` when `len(elems) < 2`), so it is answered the
        # same way here rather than refused: the C prototype decides what the
        # register means, and refusing a form the compiler that does have C
        # types accepts would make the two disagree about the language.  The
        # symbol is still read, so a well-formed one-element bracket is a call.
        head = items[0]
        if not isinstance(head, F.StringLiteral) \
                or not isinstance(getattr(head, "value", None), str):
            return (None, None, _non_literal_symbol_why(head))
        return (head.value, EXTERN_RETURN_VOID, None)
    head = items[0]
    if not isinstance(head, F.StringLiteral) \
            or not isinstance(getattr(head, "value", None), str):
        return (None, None, _non_literal_symbol_why(head))
    symbol = head.value
    text = type_expr_text(items[1])
    if text is None:
        return (None, None,
                f"declares its return type as {_spell(items[1])}, which is not "
                f"a type this path can read. The declared return type is what "
                f"says how wide the value coming back in the return register "
                f"is, so a type the build cannot name leaves the width "
                f"unestablished — and a call whose result is an unestablished "
                f"number is a plausible wrong answer rather than a failure")
    kind = external_call_return_kind(text)
    if kind is None:
        return (None, None,
                f"declares its return type as {text}, and this path has no "
                f"value of that kind to put in the return register. A formal "
                f"value is one 64-bit word, so the width of what comes back "
                f"has to be established by the declaration: an integer type "
                f"extends the register to its own width, a pointer is the "
                f"whole of it, and anything else would have to drop or invent "
                f"bits. Declare one of those, or keep the value on the other "
                f"side of the boundary")
    return (symbol, kind, None)


def external_call_result_value_kind(call):
    """The value KIND a lowered `external_call[…]` call's result HOLDS, or None.

    `external_call_return_kind` answers what the return REGISTER means — a word,
    an integer of a stated width, or nothing at all — and that is a marshalling
    fact. This answers what the word holds, which is the question every consumer
    of a KIND asks (`ValueKinds.kind_of`, and through it `print`, the string
    methods, `String(x)` and `%s`). The two cannot be one answer: `EXTERN_RETURN_
    WORD` is a 64-bit integer and a pointer alike, so a caller that reads the
    marshalling kind as a value kind has to guess, and the guess this replaces
    was the "a word is an integer" default.

    Only POSITIVE evidence is returned, and None is the conservative direction
    for the reason `string_conversion_refusal` gives: this is a value model that
    refuses rather than misreads, but "this path cannot classify the result" is
    the answer the existing default already gives and it is not made worse here.

      * a declared STRING type is `char *`, so `STR_KIND`;
      * a declared POINTER whose FIRST type argument is a byte (`BYTE_POINTER_
        ELEMENTS`) is a `char *` too, so `POINTER_KIND` — the same
        representation, the same `%s` and `strcmp`, with a truthiness that is
        the pointer's own NULL test rather than a `strlen` (`POINTER_KIND`'s own
        comment carries the measured SIGSEGV that separates the two);
      * every other declaration (a wider pointee, an integer, a struct this path
        cannot word) is None, which leaves the caller's existing answer exactly
        where it was.

    Measured on the defect this closes, both architectures: `var ptr =
    external_call["getenv", _CPointer[UInt8, UntrackedOrigin[mut=False]]](name)`
    bound `ptr` to the integer default, so `String(unsafe_from_utf8_ptr=ptr)` was
    refused as "the identity on one that is not [text]" about the one shape that
    is — a `char *getenv(const char *)` — and `std/os/env.mojo`'s own transcribed
    round trip
    (`test_formal_external_call.py::env_round_trip`) stopped building.
    """
    if not isinstance(call, F.CallExpr):
        return None
    spec = external_call_spec(call.func)
    if spec is None:
        return None
    _symbol, return_kind, why = spec
    if why is not None or return_kind in (None, EXTERN_RETURN_VOID):
        return None
    items = (list(call.func.index.elements)
             if isinstance(call.func.index, F.TupleExpr) else [call.func.index])
    if len(items) < 2:
        return None
    text = type_expr_text(items[1])
    if text is None:
        return None
    base = annotation_base_name(text)
    if base is None:
        return None
    if base in STRING_TYPE_CTORS:
        return STR_KIND
    if base in POINTER_TYPE_CTORS:
        if annotation_type_arg_base(text, 0) in BYTE_POINTER_ELEMENTS:
            return POINTER_KIND
        return None
    return None


def _non_literal_symbol_why(head) -> str:
    """The clause for an `external_call` bracket whose first element is not a
    string literal. Its own function so the one-element and the two-element
    bracket cannot drift into refusing the same thing differently."""
    return (f"names the symbol to call with {_spell(head)}, which is not a "
            f"string literal. A branch has to be emitted against a symbol the "
            f"build can read, and a name bound by a `comptime` parameter is "
            f"not one at the point this call is lowered — the call would go to "
            f"wherever that name's value happened to point. Spell the symbol "
            f"as a literal, or call through a function pointer the module "
            f"declares")


def external_call_spelling(e) -> str:
    """`e` as a diagnostic should write it: `external_call["sym", Int32]`.

    One reader for the two shapes the bracket can have — a bracketed comma list
    is a tuple index, anything else a single index — so every refusal, on every
    call site and both architectures, writes the same construct the same way.
    """
    if is_multi_index(getattr(e, "index", None)):
        return multi_index_spelling(e)
    return f"external_call[{_spell(e.index)}]"


def external_call_refusal(spelled: str, why: str) -> str:
    """The refusal for an `external_call[...]` that is the right construct and
    the wrong shape. Arch-free, from this module like every other one, because
    the two architectures have to refuse the same construct for the same
    reason — the failure this path has already produced once, where arm64 said
    no and x86-64 emitted a `call` to a symbol the source never named.
    """
    return (f"{spelled} {why}")


def external_call_value_refusal(spelled: str) -> str:
    """The refusal for an `external_call[...]` read as a VALUE.

    Separate from `external_call_refusal` because it is a different mistake: the
    template is perfectly well formed and the source is using it as something
    it is not.  `multi_index_refusal_for` cannot catch this one — it sees a
    SubscriptExpr with no parent — so each backend asks at the point the
    address would be computed, which is the last moment the shape is still
    visible.
    """
    return (
        f"{spelled} is applied as a value. The bracket names a C symbol and a "
        f"declared return type; it is not a container, and the value the call "
        f"produces is the C function's, which only a CALL can ask for — there "
        f"is nothing here to read, and an address into a frame that the source "
        f"never mentioned would be a number with no meaning. Call it"
    )




# ── Calling convention ────────────────────────────────────────────────────
#
# On both formal paths a generic function's comptime parameters are ordinary
# LEADING arguments: the call site evaluates the bracket expressions and passes
# them first, so the body reads them through the normal parameter machinery.
# The ORDER is a language decision and lives here; how many arguments the
# platform can pass in registers is the backend's business (AAPCS gives 8,
# SysV gives 6).


def incoming_args(fn) -> list:
    """(name, type_or_None) for each incoming argument, in ABI order.

    Comptime parameters first (type None — they are already full words, with
    no declared width to normalize to), then the runtime parameters."""
    ct = []
    for p in (getattr(fn, "comptime_params", None) or []):
        if isinstance(p, str) and p.isidentifier():
            ct.append((p, None))
    return ct + list(getattr(fn, "params", None) or [])


def call_callee_name(func) -> str | None:
    """The name of the function a call names, for the two spellings that name
    one: a plain `f`, and a comptime specialization `f[a, b]` of one.

    `None` for every other callee, and the exclusions are the point rather than
    an omission:

      * `recv.m(x)` — a METHOD call. Its name lives in the method table
        (`_method_owners`), not here, and a MemberExpr is also how `mod.f(x)`
        spells a module-level function, which is a different question again.
      * `mod.f[a](x)` — a specialization of a dotted name. arm64's
        `_specialization_of` answers a dotted name for it and lowers it to a BL
        against that symbol; there is no parameter list for a dotted name here
        either, so `None` is the answer that keeps the two from disagreeing
        about what is being called.
      * a computed callee (`f()[0](x)`, a lambda, a tuple index) — no name at
        all, which `frame_opaque_position_refusal` says in its own words.

    **Why the subscript is safe to look through, which is what makes this worth
    having.**  `incoming_args`, immediately above, puts a generic's comptime
    parameters FIRST, and the call site passes them first — so the brackets
    contribute no *call-time* argument and call-time position `i` is the `i`th
    entry of `function_param_shape(fn).names`, which is the list every frame
    table in `formal/build.py` is keyed by.  Measured on arm64 before this
    function existed, because the answer had to be a fact rather than a reading:
    `def f[type: Int](x: Int, y: Int)` called as `f[1](3, 7)` returns 307, with
    `type`=1, `x`=3 and `y`=7, and each of the three read back correctly on its
    own.

    **It is the analysis's copy of what the EMITTER will call**, which is the
    reason it is here and not written out again per reader.  arm64's
    `_callee_symbol` answers the same two shapes this way (`_specialization_of`
    → `specialization_name`), and an analysis that disagreed with its own
    emitter would be reasoning about one call while the machine makes another.
    x86-64's `_callee_symbol` deliberately does NOT — see the bug doc this is
    filed with; there it is a refusal, and it has to stay one."""
    if isinstance(func, F.IdentExpr):
        return func.name
    if isinstance(func, F.SubscriptExpr) and isinstance(func.obj, F.IdentExpr):
        return func.obj.name
    return None




# ── Shifts ───────────────────────────────────────────────────────────────
#
# A shift is the one operator whose result depends on a value BOTH backends
# have to agree about and neither can read off an instruction. The hardware
# takes the amount modulo the word size, so `LSRV Xd, Xn, Xm` with `Xm = 64`
# is a shift by ZERO, `3 >> 64` is `3`, and `3 << 64` is `3` — on arm64 and on
# x86-64 alike, because both were written to the same wrong rule rather than
# because the rule is the hardware's (“FORMAL_shift_by_64_or_more_wraps_instead_of_saturating: `3 >> 64` is `3`”).
#
# It is here, in the shared model, because a per-backend fix is the one shape
# that cannot be verified: the two shift emitters are separate functions with
# the same structure, so a rule written twice is two rules that agree only
# until one of them is edited. THIS is a value-model decision (what the
# operator means), not instruction selection, which is the split this module
# exists to enforce.
#
# The rule is CPython's, because CPython is the oracle every test in this tree
# compares against: a shift by an amount at or beyond the word's width
# SATURATES.
#
#   x << n  ==  0            for n >= 64, signed or unsigned
#   x >> n  ==  0            for n >= 64, when x is non-negative
#   x >> n  ==  -1           for n >= 64, when x is negative
#
# The last row is the one that is easy to get wrong, and it is why the rule
# cannot be a bare "return 0": Python's `>>` on a negative value is an
# ARITHMETIC shift (it rounds toward negative infinity — `-5 >> 1` is `-3`,
# not `-2`), so the sign bit keeps being replicated no matter how far the
# shift goes, and the answer at 64 is the sign extended word, which is `-1`.
# A saturation that returned 0 for every amount at or past 64 would be right
# for `x << n` and for every non-negative `x >> n`, and wrong for exactly the
# negative operands that a bit-manipulating algorithm produces by subtracting.
#
# Note what is deliberately NOT here: the spelling for a LOGICAL right shift.
# `>>` is arithmetic on a signed value and that is not a defect — it is what
# Python means, and `test_formal_run.py` pins both directions so a "fix" that
# made every `>>` logical would be caught. A program that wants zeros shifted
# in says so with an unsigned type, which is what `shift_signedness` is for.

# The width a shift saturates at, and the amount the hardware masks to.
SHIFT_WIDTH = 64
SHIFT_AMOUNT_MASK = 63

# The status a trapped run-time fact leaves behind. It is the SAME status the
# divide-by-zero arm of each backend's shift/div emitter already exits with, so
# "this program could not be answered" is one answer on this path rather than
# one per check — and it is a named constant rather than a literal repeated in
# four emitters, because the test asserts the two architectures AGREE on it and
# a literal in each arm is how they would stop agreeing.
SHIFT_TRAP_STATUS = 1


def shift_saturates(amount, width: int = SHIFT_WIDTH) -> bool:
    """Whether a shift by `amount` is at or past the word's width.

    `amount` is whatever the source says: a Python int, possibly a variable's
    unknown value (None, which is never saturating) or a negative one. A
    negative amount is NOT saturating here — `shift_amount_is_trap` is what
    decides that one, and asking this function about it would be asking the
    wrong question: an amount past the width is a VALUE this path knows how to
    answer, and an amount below zero is a fact it has no value for."""
    return amount is not None and amount >= width


def shift_amount_is_trap(amount) -> bool:
    """Whether a shift AMOUNT is one this path refuses rather than masks.

    The third of the three answers a shift amount can have, and the only one
    of them that is not a value: an amount at or past the word's width
    SATURATES (`shift_saturated_is_zero`) and an amount in range SHIFTS, but a
    NEGATIVE amount is not a shift distance at all. CPython raises
    `ValueError: negative shift count` for it, and the answer this path had
    instead was the hardware's: `LSL`/`ASR`/`LSR` use the low six bits of the
    shift register, so `-1 & 63` is 63 and `1 << -1` was `1 << 63` —
    `-9223372036854775808`, a plausible high-bit-set word rather than a
    failure, and `8 >> -1` was `0`.

    The SIGN is a run-time fact (the amount is usually a variable), so this
    function is asked about a static amount and the emitters ask the same
    question of the register with a signed compare. It is `True` for a
    statically-known negative amount and `False` for an unknown one (None) or a
    non-negative one.

    A "saturate to 0" answer would be a fabrication rather than an
    approximation, and it is worth saying why rather than leaving it as an
    option: `x << -1` is not `0` in any reading, and answering 0 would be as
    wrong as answering `1 << 63`. It is also the answer a saturation rule
    written with an UNSIGNED compare gives — a negative amount is below 64
    unsigned's way round — which is the specific trap this shape is separated
    from `shift_saturates` to keep out of."""
    return isinstance(amount, int) and not isinstance(amount, bool) \
        and amount < 0


def negative_shift_refusal(op: str, amount) -> str:
    """The build-time refusal for a shift by a statically negative amount.

    A literal amount is decidable before anything is emitted, and a build-time
    diagnostic NAMES THE LINE where a run-time trap can only say "something
    went wrong" — so the two are not alternatives, and this is the one that
    fires when the build can decide. The run-time trap (`SHIFT_TRAP_STATUS`,
    read by both backends' register-form shift emitter) is what covers the
    variable amount, which is the common case.

    One wording for both architectures, from `model.py` rather than from each
    emitter, for the reason every other rule here lives here: a diagnostic that
    differs between the two backends is not a diagnostic, it is two facts about
    one construct."""
    mask_bits = SHIFT_AMOUNT_MASK.bit_length()
    return (f"a shift by a negative amount: `{op} {amount}` shifts by "
            f"{amount}, which is not a shift distance — CPython raises "
            f"`ValueError: negative shift count` for it, and this path has no "
            f"value to answer with, since the hardware masks the amount to its "
            f"low {mask_bits} bits and answers a different shift entirely. The "
            f"amount has to be a non-negative distance, which a program "
            f"computes with `& {SHIFT_AMOUNT_MASK}` or a conditional of its "
            f"own")


def shift_saturated_is_zero(op: str, signed: bool) -> bool:
    """Whether a shift that saturates answers 0, whatever the value was.

    True for `<<` (every bit is shifted out) and for a LOGICAL `>>` (the
    zeros come in). False only for an ARITHMETIC `>>` of a signed value,
    where the answer is the sign-extended word — 0 for a non-negative
    operand and -1 for a negative one — because Python's `>>` on a negative
    value rounds toward negative infinity and keeps replicating the sign no
    matter how far the shift goes. Returning 0 for a negative operand is
    precisely the wrong answer, which is the whole reason this asks the
    question in this shape.

    The backend needs to know whether the answer is a CONSTANT 0 it can
    materialise in one instruction, or a run-time fact (the operand's sign
    bit) that has to be computed. Asking for the value itself would need the
    value, and the value is in a register at that point rather than in hand.

    BOTH backends branch on this rather than writing `if op == "<<" or not
    signed` themselves, because that test IS the rule and a second copy in a
    second backend is the same duplication that let `y <<= 64` and
    `y << 64` disagree about the same operator. See
    `shift_signedness` for the other half of the rule."""
    return op == "<<" or not signed


def shift_signedness(left_type):
    """The signedness that decides what `>>` shifts IN — from the LEFT
    operand ALONE, never from a promotion of both operands.

    This is the second half of the shift rule above, and it is a separate
    decision from the saturation one because it has a different cause.

    Both backends ask `cmp_signed(common_type(ttype(left), ttype(right)))`,
    and `common_type` is signed-wins (`formal/types.py`). That is the right
    rule for an ARITHMETIC operator, where the two operands genuinely
    combine. It is the wrong rule for a shift, because the right operand of a
    shift is not a value being combined with the left one — it is a COUNT.
    How many bits to move says nothing about what to move them in, and
    promoting a count into the decision is how `UInt64 >> Int` came to
    compute `0xFFFFFFFFFFFFFFFF >> 4` as `0xFFFFFFFFFFFFFFFF` (an arithmetic
    shift) where the answer is `0x0FFFFFFFFFFFFFFF` (a logical one): the
    amount was an unannotated `int`, i.e. signed, and signedness won the
    promotion and then decided the fill.

    Measured, on both backends, over the shapes that differ only in the
    amount's declared type:

        x: UInt64, n: Int      x >> 4   0xffffffffffffffff   WRONG
        x: UInt64, n: UInt64   x >> 4   0x0fffffffffffffff  right
        x: UInt64, n: literal  x >> 4   0x0fffffffffffffff  right

    The literal row is the diagnostic: it is the same shift, and the amount
    is the same number 4, so the only thing that changed between the wrong
    row and the right one is whether the count was TYPED. A count that
    happens to agree with the answer is not a reason to give the right
    answer.

    So: the left operand decides, and the right one is not consulted. For an
    unannotated `int` left operand that is signed, which is right — Python's
    `>>` on a negative value IS arithmetic, and `test_formal_run.py` pins
    that so a "fix" that made every `>>` logical would fail. For a declared
    unsigned left operand the value cannot be negative, so a logical shift is
    not merely correct but the only thing that can be.

    The parameter is the LEFT OPERAND'S TYPE, not a bool: the backends pass
    `types.cmp_signed(...)` of it, and keeping the decision here means the
    two cannot pick different notions of "the type of the thing being
    shifted"."""
    return left_type


def division_floors(op: str, signed: bool) -> bool:
    """Whether a `/`, `//` or `%` on operands of this signedness needs the FLOOR
    correction — the `SDIV`/`IDIV` truncates, and the source says otherwise.

    Three answers, and the third is why this is one function rather than an
    `if op == "//"` in each backend:

      * **unsigned** → False, and not as a shortcut: for two non-negative
        operands truncating toward zero and flooring are the SAME function, so
        `UDIV`/`DIV` is the answer and a correction would be a no-refusable
        cost. This is why the emitters gate on `signed`;
      * **`//` and `%` on a signed operand** → True. `//` floors and `%` takes
        the sign of the DIVISOR, so `7 // -2` is `-4` and `7 % -2` is `-2`
        where truncation answers `-3` and `1`. The correction is
        `q - c` / `r + d*c` with `c = 1` when the remainder is non-zero and
        the operands' signs differ, and no encoding containing a hardware
        divide can express it — which is why it is a sequence of `CMP`/`CSET`
        on both machines rather than a different divide;
      * **`/` on a signed operand** → False, and this is a DOCUMENTED
        LIMIT rather than a rule: there is no float on this path
        (`FORMAL.md` §6 Phase 7), so `/` is the int-only truncation and
        `0 - 7 / 2` answers `-3` where CPython answers `-3.5`. Reading `/`
        as `fdiv64` would make it agree with `//` and disagree with CPython
        in a new place, so the row stays where the phase-7 limit already
        puts it.

    BOTH backends ask this, for the reason `shift_saturated_is_zero` gives
    above: that test IS the rule, and a second copy in a second backend is how
    `y <<= 64` and `y << 64` came to disagree about one operator. Here the
    failure it would have produced is worse than a disagreement about a
    shift: a backend that corrected `//` and not `%` (or `//` and not `/`)
    would answer a dividing program from two different notions of Python's
    integer division, on the same machine, in the same function.
    The correction's instruction sequence is each backend's
    `_emit_floor_correction` (arm64 and x86-64, the same six instructions and a
    different tail because `IDIV` consumes the dividend), and the source model's
    half is `fdiv64`/`frem64` in `lib/ProofLib.lean`, whose `fdiv_correction` is
    the same 0-or-1 word spelled over `sdiv64`."""
    return bool(signed) and op in ("//", "%")


def division_needs_zero_guard(denominator) -> bool:
    """Must this `/`, `//` or `%` emit the divide-by-zero test?

    `False` only when the DENOMINATOR is a literal integer the emitter already
    folded, and not zero. Everything else — a variable, a folded expression
    this file cannot evaluate, a zero literal — needs the guard, because
    `SDIV`/`UDIV`/`IDIV`/`DIV` by zero is not defined by A64 or by Intel and the
    program is entitled to the trap.

    **Why it is asked at all, which is the cost side.** The guard is not two
    instructions. Its taken arm is the divide-by-zero EXIT, and on arm64
    `_emit_exit` begins with a `bl fflush` — an extern call, which
    `arm64_proof_gen.py::_unfollowable_calls` classifies as `opaque` because the
    target is outside the image. **The walk discharges ONE such call by halting
    at it**, so a function containing TWO divisions carried two unfollowable
    calls and the universal theorem stopped generating, by name:

        universal theorem: 2 calls this walk cannot follow
        (0x10000046c -> 0x100000508 (opaque), 0x1000004d8 -> 0x100000508
        (opaque)), and ONE halt address cannot discharge them

    Measured, and the shape is not about division at all — it is the same
    refusal a two-`print` program gets, because it is the same two-calls rule.
    `n // 7` alone generates a proof; `n // 7 + n % 7` and `n // 7 + n % 3` do
    not. `formal/examples/floordiv.mojo` and `udivmod.mojo` were red in
    `test_formal.py` for exactly this and for nothing about a floor correction.

    So the fix available without the `lib/ProofLib.lean` change
    `bugs/FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`
    asks for is to stop emitting a guard that cannot fire: for `// 7` there is
    no zero to trap, and the `bl fflush` that made the theorem unprovable goes
    with it. **What this does NOT do is fix a two-call program whose calls are
    real** — that document's own precondition, unchanged, and it is a library
    change rather than an emitter one.
    """
    return not (isinstance(denominator, int) and denominator != 0)


def division_needs_overflow_precheck(numerator, denominator) -> bool:
    """Must this `//` emit the overflow pre-check, or has the build already
    decided the one overflowing pair cannot be the pair?

    The pre-check is the sentinel `dividend == INT64_MIN and divisor == -1` —
    the one exact pair whose quotient, 2**63, does not fit
    (`division_overflow_refusal` is the build-time spelling of the same
    decision, and it has already raised by the time the emitter asks this).
    Each half of the sentinel is dead as soon as the build decides the operand
    away from the overflowing value:

      * a LITERAL denominator that is not `-1` kills the first half — no such
        division can overflow, whatever the dividend;
      * a LITERAL numerator that is not `INT64_MIN` kills the second half — no
        such division can overflow, whatever the divisor.

    Everything else needs the check, because the build cannot decide either
    half and the word the hardware computes is the trap's subject.

    **Why it is asked at all, which is the cost side.** The pre-check is not
    two compares. Its taken arm is the overflow TRAP, and on arm64
    `_emit_exit` begins with a `bl fflush` — an extern call, which
    `arm64_proof_gen.py::_unfollowable_calls` classifies as `opaque` because
    the target is outside the image — exactly the shape
    `division_needs_zero_guard` refuses to emit for a divisor that cannot be
    zero. `test_formal_call_proof_gen.py`'s
    `TestTheZeroDivisorGuardIsAFalseGoal` measures it for the sibling row: a
    `// 4` image must carry no out-of-image call, and a sentinel whose divisor
    half is dead by a literal re-adds the trap's flush and puts the universal
    theorem back behind the two-calls rule. The decision is the WHOLE pair's
    deadness rather than per half, because the emission is one block: a
    `// -1` program's dividend is still unknown, so the check goes, and a
    `// 4` program's whole sentinel is dead, so it does not.
    """
    if isinstance(denominator, int) and denominator != -1:
        return False
    if isinstance(numerator, int) and numerator != INT64_MIN:
        return False
    return True




# ── Integer OVERFLOW: CPython is unbounded and a word is 64 bits ──────────
#
# Every other rule in this file is about what an operator MEANS. This one is
# about what happens when the answer does not fit, and it is here because it is
# the one arithmetic fact both backends got wrong in the same direction, with
# no diagnostic, on both machines.
#
# CPython's `int` is arbitrary precision: `2**64` is 18446744073709551616 and
# `9223372036854775807 + 1` is 9223372036854775808, both exact. A formal value
# is ONE 64-bit word (`doc/ABI.md`, "Scalar types"), so `ADD`/`SUB`/`MUL`/
# `LSL`/`SDIV` produce the answer MODULO 2^64 and nothing downstream can tell.
# MEASURED on this tree before the rule below existed, both backends, same
# program, same silence (exit 0, no message, a plausible number):
#
#     9223372036854775807 + 1     CPython  9223372036854775808   arm64 0
#     0 - 9223372036854775807 - 2  CPython  -9223372036854775809  arm64 -1
#     4000000000 * 4000000000      CPython  16000000000000000000  arm64 1983905792
#     1 << 63                      CPython  9223372036854775808   arm64 0
#     1 << 64                      CPython  18446744073709551616 arm64 0
#     2 ** 64                      CPython  18446744073709551616 arm64 0
#     int("9223372036854775808")   CPython  9223372036854775808   arm64 -1
#     -2**63 // -1                 CPython  9223372036854775808   arm64 0
#                                                        x86-64   SIGFPE
#
# The last row is the shape of the whole list: ONE source, TWO architectures,
# and they do not even fail the same way — arm64 wraps to 0 because `SDIV`
# defines the result, and x86-64 dies on the `IDIV` overflow trap. A backend
# that disagrees with CPython is a defect; two backends that disagree with each
# other about WHICH wrong answer to give is the worse one, because there is
# then no single number to look for.
#
# **The decision is a TRAP, not exact semantics and not a wider word.** Exact
# semantics is a heap-allocated bignum behind every value, which contradicts
# the whole of `doc/ABI.md` (a formal value is one word; it crosses a register,
# a frame slot and a module dylib boundary in one). A wider word is not
# available. What IS available is the pattern this path already uses for every
# other bounded operation it cannot answer — `SHIFT_TRAP_STATUS` for a shift
# amount that is not a distance, `int_parse_trap_message` for a string that is
# not an integer, `list_append_overflow_message` for a list that is full: say
# WHICH bound was hit on fd 2 and stop with a non-zero status. That is not
# CPython's `OverflowError` — this path has no way to raise, and every
# diagnostic here says so — but it is the difference between "this program has
# no answer on this target" and "this program silently printed a wrong number",
# and only the second one is a miscompile.
#
# **What is NOT trapped, and why each exclusion is a decision rather than a
# gap.** Trapping every `+` would be as wrong as wrapping every one:
#
#   * a NARROW type (`Int8`…`Int32`) — wrapping is what the type MEANS. Mojo's
#     `Int8` is a declared 8-bit type, the value is a bit pattern, and
#     `x: Int8 = 127; x + 1` is -1 in every Mojo that has `Int8`. The rule
#     asks the RESULT type, so the promotion decides it: two `Int32` operands
#     promote to `Int32` and wrap, and that is right.
#   * an UNSIGNED 64-bit type (`UInt64`) — same reason, and stronger: the
#     source spelled the wrap down. There is no unsigned CPython to disagree
#     with.
#   * POINTER arithmetic — `p + 1` on a `Pointer[Int64]` is an ADDRESS, and
#     address arithmetic wraps by definition: the last element of an array
#     plus one is a one-past-the-end pointer, and a one-past-the-end pointer
#     is not an overflow. `pointer_offset_scale` is what tells the emitters
#     this (they already call it on the same two lines), so the exclusion is
#     one predicate rather than a type test that would have to know what a
#     pointer looks like in every spelling.
#
# **The one place the trap is NOT enough, and what happens instead.** `<<` and
# `**` with a LITERAL amount are decided by the build: `1 << 64` and `2 ** 64`
# overflow for every value of the base, so a refusal naming the line is both
# possible and better than a status code. `literal_overflow_refusal` is that
# message. The run-time trap covers the variable-amount spelling, where the
# build cannot know.

#: The machine word's signed range. `Int` is `int64_t` (`doc/ABI.md`), so these
#: are the two values CPython's `int` cannot be represented as.
INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1

#: The width of the word an `Int` occupies, as a named constant rather than the
#: `64` that appears in `SHIFT_WIDTH` two hundred lines above and in
#: `doc/ABI.md`'s scalar table. `int_overflow_traps` asks "is this result type
#: at least a full word", and a literal `64` in that question is a second place
#: for the word's width to be edited.
INT_WORD_WIDTH = 64

#: The operators whose word result can leave the signed 64-bit range. `&`, `|`,
#: `^`, `~`, `>>`, `%`, `/` and unary `-` are NOT here and the reasons are worth
#: the space, because "the same rule for every operator" is the obvious mistake:
#:
#:   * `&` `|` `^` `~` are BITWISE — every answer is a function of the same bit
#:     positions of the operands, so the result is in range whenever the
#:     operands are.
#:   * `>>` on a signed value is arithmetic and Python floors, so it moves
#:     TOWARD negative infinity and can only leave a non-negative operand
#:     negative, never the other way — `shift_saturated_is_zero` already
#:     spells the saturating end of it.
#:   * unary `-` overflows for exactly ONE operand, `INT64_MIN`, and that one
#:     is a build-time decidable constant whenever the source writes it; the
#:     runtime spelling reads a variable and is handled by `abs`/negation of a
#:     value that is already in range.
#:   * `//` IS here, and in exactly ONE case: `INT64_MIN // -1` is 2**63, one
#:     past the largest word — the only division whose answer does not fit,
#:     which is why `division_overflow_refusal` is so narrow. The `+`/`-`/`*`
#:     relatives overflow on ANY pair of large enough operands; this one needs
#:     the one exact pair.
#:   * `%` is NOT: the floored remainder is always in range — it is below
#:     `|divisor|` in magnitude — so `INT64_MIN % -1` is 0 and the division
#:     arm must not trap it. (x86-64's `IDIV` still raises `#DE` before it can
#:     answer that 0; the pinned divergence is `test_formal_int_semantics.py`'s
#:     `mod_min_by_minus_one` row, and it is not this predicate's.)
#:   * `/` is NOT: it is this path's DOCUMENTED int-only truncation (the
#:     `slash_truncates` row) — a divergence with its own pinned row, not a
#:     miscompile to trap.
INT_OVERFLOW_OPS = ("+", "-", "*", "//")


def int_value_fits(result_type, value) -> bool:
    """Whether CPython's `value` is representable as a word of `result_type`.

    The question is asked of the RESULT type because that is the type the
    promotion chose, and the promotion is what decides whether the hardware
    keeps the whole answer: `int_overflow_traps` below asks this for the
    result of the operation, so `x: Int32 = 127; y = x + 1` is asked about
    `Int32` and answers "fits", while the same two values read as `Int` is
    asked about `int64_t`.

    An UNSIGNED type's range is `[0, 2**w)` and a SIGNED one is
    `[-2**(w-1), 2**(w-1))`, which is the same statement about a different
    zero point. Both are answered here rather than only the signed one, because
    the caller that asks the general question (`fold_overflow`) asks it before
    it has decided anything else, and a function that answered True for every
    unsigned value because "only the signed case is asked" would be a second
    implementation of the answer rather than a generalisation of it."""
    t = resolve_type(result_type)
    if t.signed:
        lo, hi = -(2 ** (t.width - 1)), 2 ** (t.width - 1) - 1
    else:
        lo, hi = 0, 2 ** t.width - 1
    return lo <= value <= hi


def resolve_type(t):
    """`types.resolve` without the import: model.py imports no formal module.

    `formal/types.py` imports THIS module, so importing it back here would be
    a cycle; `model.py` has always read a `None` type as "the default"
    (`literal_default_word`, `optional_none_word` and the `NONE_WORD` family all
    do), and this is that reading in one named place. The default is the signed
    64-bit word, which is `types.DEFAULT_INT_TYPE` and the only width for which
    `int_overflow_traps` is ever True — so a `None` reaching this function is
    the trapping case, which is the safe direction."""
    if t is None:
        return _DEFAULT_INT_TYPE
    if getattr(t, "width", None) is None:
        return _DEFAULT_INT_TYPE
    return t


class _IntTypeShape:
    """The two attributes of `formal/types.py`'s `IntType` this module reads.

    A tiny stand-in rather than the class itself, for the reason in
    `resolve_type`: `types` imports `model`, so `model` cannot import `types`.
    Duck-typed on `width`/`signed`, which is all `int_value_fits` and
    `int_overflow_traps` look at, and which makes a caller that passes the
    real `IntType` work unchanged."""
    __slots__ = ("width", "signed")

    def __init__(self, width: int, signed: bool):
        self.width = width
        self.signed = signed

    def __eq__(self, other):
        return (isinstance(other, _IntTypeShape) and other.width == self.width
                and other.signed == self.signed)

    def __repr__(self):                                   # pragma: no cover
        return ("Int" if self.signed else "UInt") + str(self.width)


_DEFAULT_INT_TYPE = _IntTypeShape(64, True)


def int_overflow_traps(op: str, result_type, *,
                       pointer_arith: bool = False) -> bool:
    """Whether `op` on these operands must refuse rather than wrap.

    The ONE predicate both backends ask before they emit an overflow check, and
    it is a predicate rather than a formula written out twice for the reason
    `division_floors` gives above: a rule written per backend is two rules that
    agree until one of them is edited.

    The answer is True for `+`, `-`, `*` and `//` on a result the word cannot
    hold — a signed 64-bit one — and False for every case the "What is NOT
    trapped" list above gives a reason for. Read in order, that is:

      1. not one of `INT_OVERFLOW_OPS` → False;
      2. `pointer_arith` → False (an address, and the caller is the one that
         knows: `model.pointer_offset_scale` is the same predicate the emitter
         uses to decide to SCALE the offset, so the two cannot disagree about
         whether it was a pointer);
      3. the result type is not signed-64 → False (a narrow or unsigned type
         wraps by definition);
      4. otherwise → True.

    **It takes the RESULT type and not the operand types**, and the tempting
    alternative — "the left side is an `Int8`, so `a + b` cannot overflow" — is
    wrong twice over: the promotion has already happened by the time this is
    asked (`a + b` with an `Int8` and an `Int64` is an `Int64` operation), and
    CPython's `int` has no narrow types at all, so there is no source that
    could be asking for a narrow result. A parameter for the operand types
    would be a second place for the rule to be edited, which is the thing this
    function exists to prevent.
    """
    if op not in INT_OVERFLOW_OPS:
        return False
    if pointer_arith:
        return False
    t = resolve_type(result_type)
    return bool(t.signed) and t.width >= INT_WORD_WIDTH


#: The status a trapped run-time overflow leaves behind. It is
#: `SHIFT_TRAP_STATUS` and that is deliberate rather than a copy: "this program
#: could not be answered on this target" is ONE answer on this path, and a
#: reader who has seen a shift stop should not have to learn that an add stops
#: differently. Every diagnostic on this path — the divide-by-zero arm, the
#: shift trap, the int-parse trap, the append overflow — leaves this status.
INT_OVERFLOW_TRAP_STATUS = SHIFT_TRAP_STATUS


def int_overflow_trap_message(op: str) -> str:
    """The ONE text a run-time integer overflow writes to fd 2 before it stops.

    For BOTH backends, for the reason `int_parse_trap_message` gives: two
    architectures printing two different sentences for one limit is how a reader
    ends up looking for a construct one of them invented. It is `op`-shaped
    only in the operator it names, because that is the one fact the two
    architectures could disagree about — the trap site knows which instruction
    it came from, and saying "an overflow" without saying where would send the
    reader to `+` when it was `*`.

    The message says the three things a reader needs and no more: what the
    target cannot do, what CPython would have said, and that this is a stop
    rather than an answer. It does NOT claim to be `OverflowError`, because
    this path cannot raise — the same sentence `int_parse_trap_message` spends
    on `ValueError`, and for the same reason.
    """
    return (f"OverflowError: this program's `{op}` left the signed 64-bit "
            f"range this target has for an integer ({INT64_MIN} .. "
            f"{INT64_MAX}), and the word wrapped instead. CPython's `int` is "
            f"arbitrary precision and would have answered the exact value; "
            f"this formal image has no way to raise and no wider word to "
            f"answer with, so it stops here rather than report the wrapped "
            f"one.\n")


#: The largest power `power_overflow_refusal` will COMPUTE in order to put the
#: exact value in its message. 4096 bits is 1234 decimal digits, which formats
#: in no time and reads; past it the message carries a bit count instead, so a
#: source spelling `10 ** 10 ** 7` cannot cost a build half a minute.
_EXACT_POWER_BITS = 4096

#: How far `_digits` counts before it gives up and says "more than this". It is
#: above CPython's own 4300-digit int-to-str limit, which is the number the
#: message quotes, so "more than 5000 digits" is always a true statement about
#: a value `str` refused -- and counting to it costs 5000 divisions instead of
#: ten million.
_DIGIT_COUNT_CAP = 5000


def _digits(value: int) -> int:
    """How many decimal digits `abs(value)` has, capped at `_DIGIT_COUNT_CAP`.

    The cap is what makes this a bounded amount of work: `10 ** 10 ** 7` has
    ten million digits and counting them one integer division at a time is a
    ten-million-iteration loop inside a build. Returning the cap is honest
    because the only caller is reporting a value CPython's own `str` already
    refused, and CPython's limit is below the cap.
    """
    n, v = 0, abs(value)
    while v and n < _DIGIT_COUNT_CAP:
        n += 1
        v //= 10
    return n or 1


def _render_int(value) -> str:
    """`value` as a decimal string, or its DIGIT COUNT when CPython will not.

    A power like `10 ** 10 ** 7` has ten million digits, and CPython's own
    `int`→`str` conversion refuses above 4300 — `print(10 ** 10 ** 7)` raises
    `ValueError: Exceeds the limit (4300 digits)`. An f-string here raises the
    same thing, which would turn a refusal into a traceback out of a build: the
    message IS the answer, and a message that cannot be formatted is not one.
    So the digit count is the fallback, and it says that is what it is."""
    try:
        return str(value)
    except (ValueError, OverflowError):
        return ("a number of more than %d decimal digits (CPython's own `print` "
                "refuses it too -- its int-to-str limit is 4300)"
                % _digits(value))


def literal_overflow_refusal(op: str, value, operands=None) -> str:
    """The BUILD-TIME refusal for an operation whose exact value is already known.

    Where `int_overflow_trap_message` is the answer for a value the build
    cannot know, this is the answer where it can — and it is the better one,
    for the reason `negative_shift_refusal` gives: a refusal names the
    expression and the exact number CPython would have produced, where a status
    code can only say that something went wrong somewhere.

    The exact value is the point. `2 ** 64` is 18446744073709551616 and saying
    so tells the reader their program is one multiplication away from being
    representable and four from being readable; "an overflow occurred" does
    not. It is computed in CPython's own arbitrary precision here, which is why
    the message can carry a number the target cannot hold.
    """
    operands = operands or ()
    if len(operands) == 2:
        shown = "%s %s %s" % (spelled(operands[0]), op, spelled(operands[1]))
    elif len(operands) == 1:
        shown = "%s %s" % (op, spelled(operands[0]))
    else:
        shown = None
    return (f"an integer overflow the build can decide: "
            f"{('`%s`' % shown) if shown else ('`%s`' % op)} is "
            f"{_render_int(value)} -- a value outside the signed "
            f"64-bit range "
            f"({INT64_MIN} .. {INT64_MAX}) this target keeps an integer in. "
            f"CPython's `int` is arbitrary precision and answers it exactly; "
            f"the word this image computes in would answer the wrapped value "
            f"instead, so the build refuses rather than emit a program that "
            f"reports a different number for the same source")


def fold_overflow(op: str, left, right, result_type=None,
                  pointer_arith: bool = False) -> str | None:
    """The build-time overflow refusal for `left op right`, or None.

    The one caller of both `fold_literal_expr` and `int_value_fits`, so the
    two questions — "can the build know the value" and "does the value fit" —
    are asked together and in one place. Either operand unknown and the answer
    is None, because a refusal that fires on half a fact is a refusal that
    fires on `n + 1`.

    `right` is None for the unary spellings (`~`, unary `-`), which is why the
    fold is written over a tuple.
    """
    if not int_overflow_traps(op, result_type, pointer_arith=pointer_arith):
        return None
    nodes = (left,) if right is None else (left, right)
    vals = [fold_literal_expr(n) for n in nodes]
    if any(not isinstance(v, int) or isinstance(v, bool) for v in vals):
        return None
    try:
        value = _apply_op(op, vals[0], None if right is None else vals[1])
    except (ZeroDivisionError, ValueError, OverflowError, MemoryError):
        # A `//` by a literal zero, or `0 ** -1`. Both already have their own
        # answer elsewhere on this path (a divide-by-zero trap at run time, and
        # the zero-exponent arm of the power emitter), and neither is this
        # function's question.
        return None
    if int_value_fits(result_type, value):
        return None
    return literal_overflow_refusal(op, value, nodes)


def _apply_op(op: str, a, b):
    """CPython's own `a op b`, for the handful of operators this module needs.

    Not a re-implementation and not an `eval`: **this IS the oracle**, in the
    only process in the build that has arbitrary precision, so the operators
    are the language's own and there is no second table here to be wrong about
    `//` flooring or the sign of a `%`. The `op` comes from
    `INT_OVERFLOW_OPS` or a literal at the two call sites, never from source, so
    the dispatch below cannot be steered.

    `b is None` is the unary spelling (`~a`), and asking for a binary operator
    with no right operand is a programming error here rather than a source
    shape — hence `ValueError` and not a silent `None`.
    """
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "~":
        return ~a
    if b is None:
        raise ValueError("unary operator with a right operand")
    raise ValueError("not an integer operator: %r" % (op,))


def shift_overflow_refusal(op: str, amount, base=None,
                         operands=None) -> str | None:
    """The build-time refusal for a shift this path cannot answer as CPython does.

    Two different questions share one function because they share one shape — a
    literal amount, a base the build may or may not know, and a word that cannot
    hold the answer — and the `<<`-only rule is the whole content:

      * **the amount is at or past the word's width.** `model.shift_saturates`
        already decided the shift cannot be performed, and `_emit_saturated`
        answered it with a constant. That constant is CPython's for `>>` and a
        FABRICATION for `<<`: `8 >> 64` is 0 and `8 >> 200` is 0, but
        `1 << 64` is 18446744073709551616 and `1 << 200` is a number with 61
        digits. So a saturating `<<` is refused and a saturating `>>` keeps its
        answer, and that asymmetry is why this is a function rather than a line
        at the `_emit_saturated` call site.
      * **the amount is in range and the RESULT does not fit** — `1 << 63`,
        which does not saturate and still overflows, so the immediate form's
        `0..63` range test is not a safety test and cannot be made into one.
        Decided only when the base folds; a variable base is the subject of
        `bugs/formal/FORMAL_integer_overflow_at_run_time_is_still_untrapped.md`.

    `None` in any argument means "the build does not know", and every such case
    returns None rather than guessing: a refusal that fires on half a fact is a
    refusal that fires on `n << 3`.
    """
    if not _is_known_int(amount) or amount < 0:
        return None                      # `negative_shift_refusal`'s question
    if amount >= SHIFT_WIDTH:
        if op != "<<":
            return None                  # the saturation IS CPython's answer
        if _is_known_int(base):
            try:
                value = _apply_shift(op, base, amount)
            except (ValueError, TypeError):
                value = None
            if value is not None and not int_value_fits(_DEFAULT_INT_TYPE,
                                                       value):
                return literal_overflow_refusal(op, value, operands)
        return (f"a shift by an amount this target cannot perform: `{op}` by "
                f"{amount} needs more than the {SHIFT_WIDTH} bits an integer "
                f"has here, and CPython's `int` is arbitrary precision, so "
                f"`x {op} {amount}` is a number of more than {SHIFT_WIDTH} "
                f"bits rather than the 0 a saturating shift would answer. The "
                f"build refuses rather than emit a program that reports a "
                f"different number for the same source. (`>>` is NOT this "
                f"case: `8 >> 64` really is 0 in CPython, because a right "
                f"shift moves bits OUT and there is nothing left to keep.)")
    if op != "<<" or not _is_known_int(base):
        return None
    try:
        value = _apply_shift(op, base, amount)
    except (ValueError, TypeError):
        return None
    if int_value_fits(_DEFAULT_INT_TYPE, value):
        return None
    return literal_overflow_refusal(op, value, operands)


def _is_known_int(v) -> bool:
    """Whether `v` is an int the build DECIDED, as opposed to `None` or a bool.

    Excludes `bool` for the reason `fold_literal_expr` excludes it: `True` is
    not the integer 1 here, it is a `BoolLiteral`, and every question in this
    section is about a number the source spelled as one."""
    return isinstance(v, int) and not isinstance(v, bool)



def _apply_shift(op: str, base, amount):
    if op == "<<":
        if amount < 0 or base < 0:
            raise ValueError("not a foldable shift")
        return base << amount
    if op == ">>":
        if amount < 0:
            raise ValueError("not a foldable shift")
        return base >> amount
    raise ValueError("not a shift: %r" % (op,))




# ── `**`: the operator with the most ways to be wrong here ──────────────────
#
# Three, and they are three different defects rather than three instances of
# one:
#
#   * **a NEGATIVE exponent** answers a FLOAT in CPython. `2 ** -1` is `0.5`,
#     `(-1) ** -3` is `-1.0`, and the only integer results a negative exponent
#     has are `0 ** -1` (which RAISES) and `0 ** -2` (which is `0.0` — still a
#     float). There is no integer answer to give, and this path has no float
#     division, so the answer it used to give — a materialised `0`, from
#     `formal/arm64_codegen.py`'s `movz x0, #0` — was a number the source never
#     wrote. **REFUSED**, and that is decidable at build time whenever the
#     exponent is a literal, which is the only spelling that reaches the
#     unroller.
#   * **an exponent past the unroller's range** (`> 64`) reaches the binary
#     exponentiation loop, which wraps. `2 ** 1000` is a 302-digit number and
#     the loop answers 0. Decidable when the BASE is a literal, which is the
#     case that matters; see the note in `power_overflow_refusal`.
#   * **an exponent in range with a base that overflows** — `2 ** 64` is the
#     measured one. Also decidable when the base is a literal.
#
# What is deliberately NOT here: `pow(a, b, m)`, the three-argument form, which
# `pow_arity_refusal` refuses by arity and which is a DIFFERENT question (it
# never overflows, because every step is reduced modulo `m`). `divmod` is
# refused the same way. Both are listed in `doc/ABI.md`'s integer table as
# refusals rather than as wrong answers, which is the honest status for a
# three-argument `pow`.


def power_overflow_refusal(base, exponent, operands=None) -> str | None:
    """The build-time refusal for an integer `**` this path cannot answer.

    Asked only when the build KNOWS both operands, because without them there
    is no question to refuse: `b ** n` overflows for some `b` and not for
    others, and a build that cannot say which has no answer to give. So the
    foldable case is refused precisely, and the variable case is what
    `bugs/formal/FORMAL_integer_overflow_at_run_time_is_still_untrapped.md` is about.

    `None` means "answerable": a non-negative exponent whose exact value fits,
    or the `0 ** 0` / `1 ** anything` shapes that never overflow.
    """
    if not isinstance(base, int) or not isinstance(exponent, int):
        return None
    if exponent < 0:
        return _negative_power_refusal(exponent, operands)
    if base in (0, 1, -1):
        return None                       # 0**0 = 1, 1**n = 1, (-1)**n = ±1
    # The BIT BOUND, before the value is computed. `10 ** 10 ** 7` is a
    # ten-million-digit number and tens of seconds of build time (measured:
    # 25.9 s for the `str` of it alone), and its size is not in doubt: a
    # non-zero base of `b` bits needs `exponent * (b - 1) + 1` bits or fewer,
    # so past 64 of them it cannot fit whatever the digits are.
    #
    # Under `_EXACT_POWER_BITS` the value is still computed, because the exact
    # number is the better message and 4096 bits is a few hundred digits of
    # arithmetic. Above it the message carries the bit COUNT instead, which is
    # the same loss `_render_int` already makes for a value `str` refuses.
    bits = exponent * (abs(base).bit_length() - 1) + 1
    if bits > INT_WORD_WIDTH and bits > _EXACT_POWER_BITS:
        return literal_overflow_refusal(
            "**", "%s ** %d, which needs %d bits" % (base, exponent, bits),
            operands)
    try:
        value = base ** exponent
    except (OverflowError, MemoryError, ValueError):
        return literal_overflow_refusal("**", "a value no machine holds",
                                        operands)
    if int_value_fits(_DEFAULT_INT_TYPE, value):
        return None
    return literal_overflow_refusal("**", value, operands)


def _negative_power_refusal(exponent, operands=None) -> str:
    """Why `b ** e` with `e < 0` has no integer answer to give."""
    shown = None
    if operands and len(operands) == 2:
        shown = "%s ** %s" % (spelled(operands[0]), spelled(operands[1]))
    return (f"`{shown or 'b ** e'}` with a NEGATIVE exponent: CPython's `int "
            f"`**` answers a FLOAT there — `2 ** -1` is `0.5` and "
            f"`(-1) ** -3` is `-1.0` — because a negative exponent asks for a "
            f"reciprocal and this target has no float division to compute one "
            f"in. The `0` this path used to answer is a number the source never "
            f"wrote, and `0 ** -1` raises `ZeroDivisionError` in CPython rather "
            f"than answering `0.0`, so there is no integer to substitute for "
            f"it either. Refused rather than answered with a fabrication; "
            f"`pow(b, e)` with a non-negative exponent is the same value when "
            f"one exists")


def division_overflow_refusal(numerator, denominator, op="/",
                               operands=None) -> str | None:
    """The build-time refusal for the one division whose answer does not fit.

    `INT64_MIN // -1` is 2**63 in CPython, which is one past the largest word;
    `-2**63 % -1` is 0 and fits. A64's `SDIV` defines the overflowing case as
    `INT64_MIN` (AArch64 §4.5 does not raise), so arm64 answered
    `-9223372036854775808`; x86-64's `IDIV` raises `#DE`, so the same program
    **died on SIGFPE** — measured, exit -8 on x86-64 and exit 0 with the wrong
    number on arm64, which is the worst pair of answers one construct can have.

    Refused when the build knows both operands, which is the only case it can
    be sure of: a variable denominator may be `-1` and a variable numerator may
    be `INT64_MIN`, and the run-time half of that pair is the overflow pre-check
    the division arms now emit before the divide (the checked spelling of the
    same one-pair decision — the build decidable, the build unknown, the trap
    is the answer).
    """
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        return None
    if denominator != -1:
        return None
    try:
        value = numerator // denominator if op == "//" else numerator % denominator
    except (ZeroDivisionError, ValueError):
        return None
    if int_value_fits(_DEFAULT_INT_TYPE, value):
        return None
    shown = None
    if operands and len(operands) == 2:
        shown = "%s %s %s" % (spelled(operands[0]), op, spelled(operands[1]))
    return (f"an integer division whose exact answer does not fit: "
            f"`{shown or 'a // b'}` is {value} in CPython, one past the "
            f"largest value this target keeps an integer in "
            f"({INT64_MIN} .. {INT64_MAX}). This is the only division that "
            f"overflows — the smallest word divided by -1 — and the two "
            f"architectures do not even fail it the same way: A64's `SDIV` "
            f"defines the answer as the numerator, while x86-64's `IDIV` raises "
            f"#DE and the image dies on SIGFPE. Refused rather than emitted as "
            f"one program and a crash")


def int_parse_overflow_refusal(text_value, base=None) -> str | None:
    """The build-time refusal for `int(s)` on a string whose value does not fit.

    The parse is `strtoll`, which on overflow returns `LLONG_MAX` (or
    `LLONG_MIN`) and sets `errno = ERANGE` — so the number this path used to
    produce for `int("9223372036854775808")` was `-1`, measured, with exit 0
    and nothing on stderr: the clamped value read as an ordinary answer.
    Checking `errno` is the run-time answer and it needs another libc call
    (`__error`), which is the same unfollowable-call budget the run-time
    overflow check wants; so the foldable case is refused precisely here and
    the rest is in the bug doc.

    `base` is the parse's base, and `None` means the one-operand `int(s)`,
    which `int_parse_lowering` makes a base-10 parse.
    """
    if not isinstance(text_value, str):
        return None
    b = INT_PARSE_BASE_MIN + 8 if base is None else base
    body = text_value.strip(C_WHITESPACE)
    sign = 1
    if body[:1] in ("+", "-"):
        sign = -1 if body[0] == "-" else 1
        body = body[1:]
    if not body:
        return None
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"[:b].lower()
    if not all(ch in digits for ch in body.lower()):
        return None                     # not a number in this base at all
    value = sign * int(body, b)
    if int_value_fits(_DEFAULT_INT_TYPE, value):
        return None
    return (f"an integer parse whose value does not fit: `int(\"{text_value}\")` "
            f"is {value} in CPython, which is outside the signed 64-bit range "
            f"({INT64_MIN} .. {INT64_MAX}) this target keeps an integer in. "
            f"`strtoll` does not answer that — it clamps to the largest word "
            f"and sets `errno`, which is why `int(\"{text_value}\")` used to "
            f"answer -1 with exit 0 and nothing on stderr, a number the source "
            f"never wrote. CPython raises `OverflowError`; this path refuses "
            f"rather than report the clamp")




# ── Read before store ─────────────────────────────────────────────────────
#
# A name the allocator gives a register is a name it cannot tell the
# difference between "has a value" and "has a home". `_load_var` reads the
# register, and a register nothing ever stored into is whatever the CALLER
# left in it — not a wrong constant, but a wrong value that CHANGES WITH THE
# BUILD, which is why it is a finding rather than a cosmetic issue: the same
# source does not have one answer. Measured on this tree, arm64 and x86-64
# disagreeing about a number neither of them wrote:
#
#     for i in range(3): G = G + i      then print G
#         CPython  UnboundLocalError
#         arm64    -157679357
#         x86-64   240046802   (the same source with range(5))
#
#     x = x + 1  at file level, then print x
#         CPython  NameError
#         arm64    11
#
# The right answer for every one of these is a REFUSAL, because this backend
# has no way to raise: it emits a Mach-O image, not a Python process, and
# there is nothing in the emitted code that means "this name is unbound".
#
# So the question is asked at build time instead, and this is the analysis
# that asks it. The honest version of it is a DOMINANCE question — every path
# from the entry to the read must pass a store — which is a reachability
# computation over the function's CFG. What ships here is the
# STATEMENT-ORDER version: a strict improvement on nothing, and NOT the whole
# fix. `read_before_store`'s docstring names the shape it still misses and
# why closing that needs the other one.


def _store_names(target) -> set:
    """Every leaf name an assignment TARGET binds, as a set.

    A thin wrapper over the two things that already know how to read a target
    shape, rather than a third copy: the BARE-STRING form — which is what
    `ForStmt.target` always is, including the nested `"(a, (b, c))"` spelling
    and the comprehension generator's comma form — goes to `_target_names`
    (i.e. `_lbn_target_names`), and the node forms (`IdentExpr`, and the
    `TupleExpr`/`ListExpr` the parser builds for a parenthesised target) are
    handled here because nothing else does.

    Which is the point of the wrapper: a second implementation of the string
    form is how the loop counter went missing from the shared bound set once
    already, and `read_before_store` asking a DIFFERENT question of a
    DIFFERENT parser is how it would go missing again."""
    if isinstance(target, str):
        return set(_target_names(target))
    if isinstance(target, F.IdentExpr):
        return {target.name}
    if isinstance(target, (F.TupleExpr, F.ListExpr)):
        out: set = set()
        for el in (getattr(target, "elements", None) or []):
            out |= _store_names(el)
        return out
    return set()


def _callee_name_ids(e) -> set:
    """The `id()` of every IdentExpr that is a CALLEE, anywhere in `e`.

    A callee is a symbol reference, not a value read: `printf(...)` reads no
    local named `printf`, and `mod.f(...)` reads no local named `mod`. Both
    the bare and the dotted spelling are included, because the dotted one's
    ROOT is the same kind of thing — a module or a receiver, not a local that
    some path forgot to store.

    Collected as node identities rather than names because a name can be both:
    `xs.append(xs)` reads `xs` once as a value and once as a receiver, and a
    name-set would drop the real read along with the receiver."""
    out: set = set()
    for node in iter_nodes(e):
        if not isinstance(node, F.CallExpr):
            continue
        root = node.func
        while isinstance(root, (F.MemberExpr, F.SubscriptExpr)):
            root = root.obj
        if isinstance(root, F.IdentExpr):
            out.add(id(root))
    return out


def _expr_reads(e, bound: set) -> dict:
    """`{name: line}` for the names an expression READS, minus the ones
    `bound` says are already stored and minus the ones in CALLEE position.

    The LINE is the read's own, not the enclosing statement's, because that
    is what a reader has to go on: this defect is invisible in review, and a
    diagnostic that points at the statement rather than the read sends them
    looking at the wrong line of a program that looks correct.

    A HAND-ROLLED walk rather than `iter_nodes`, and the reason is the whole
    design of this function: `iter_nodes` yields every node and cannot be
    told to stop descending, so it also yields a comprehension's own generator
    target and reports `[i + 1 for i in xs]` as a read of an unstored `i`.
    A false refusal breaks working code, so the walk here prunes — a
    comprehension's scope is descended with its targets bound, a call's
    callee is not descended at all, and both are the two places where the
    shape of the tree is not the shape of the value flow.

    A call's callee is skipped in BOTH spellings. `f(...)` names a symbol, and
    `recv.m(...)` / `mod.m(...)` name a receiver or a module — neither is a
    read of a local, and `check_module_symbols` has its own, better-worded
    answer for a callee that resolves to nothing at all."""
    if e is None:
        return {}
    out: dict = {}

    def rec(node, live: set):
        if node is None or isinstance(node, (str, int, float, bool, bytes)):
            return
        if isinstance(node, F.IdentExpr):
            if node.name not in live:
                out.setdefault(node.name, getattr(node, "line", None))
            return
        if isinstance(node, F.Comprehension):
            inner = set(live)
            gens = getattr(node, "generators", None) or []
            for g in gens:
                inner |= _store_names(getattr(g, "target", None))
            for g in gens:
                rec(getattr(g, "iterable", None), inner)
                for cond in (getattr(g, "conditions", None) or []):
                    rec(cond, inner)
            rec(getattr(node, "element", None), inner)
            rec(getattr(node, "key", None), inner)
            return
        if isinstance(node, F.CallExpr):
            for a in (getattr(node, "args", None) or []):
                rec(a, live)
            for kw in (getattr(node, "kwargs", None) or []):
                rec(getattr(kw, "value", None), live)
            return
        if isinstance(node, F.MemberExpr):
            # `h.x` in a VALUE position reads `h`. (The receiver of a method
            # call never gets here — the CallExpr branch returns first.)
            rec(getattr(node, "obj", None), live)
            return
        for fname in (getattr(node, "__dataclass_fields__", None) or ()):
            if fname in ("line", "col"):
                continue
            v = getattr(node, fname, None)
            if isinstance(v, list):
                for x in v:
                    rec(x, live)
            else:
                rec(v, live)

    rec(e, set(bound))
    return out


def _merge_reads(into: dict, more: dict) -> None:
    """Union two read maps, keeping the FIRST line seen for a name."""
    for name, ln in more.items():
        into.setdefault(name, ln)
