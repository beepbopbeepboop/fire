"""The formal backends' shared value model and calling convention.

The two formal targets (arm64 and x86-64) are separate code generators, but
they are ONE language implementation: the same Mojo program must mean the same
thing whichever one compiles it. Everything that decides *what a value is* —
rather than *which instruction computes it* — therefore lives here, and each
backend is left with instruction selection only.

What belongs here, and what does not:

  * HERE: the in-memory layout of a container, the rules for comparing and
    scanning keys, the order of incoming arguments, which operators exist at
    all, and the source constructs that are no-ops in the value flow.
  * PER-BACKEND: the registers, the encoders, the instruction forms, and the
    number of argument registers the platform's ABI has.

Why it matters, concretely: if arm64 scanned a dict's membership at stride 8
while x86-64 scanned at stride 16, the same `k in d` would answer differently
per architecture — a silent divergence between two backends of one compiler,
which is the failure mode this project cannot have. The same applies to the
argument order of a generic function: a callee's comptime parameters are
leading arguments on BOTH paths, so the caller and callee must agree on that
order in one place, not twice.
"""

import os

import fire_compiler as F


class CodegenError(Exception):
    """A construct this formal path refuses to lower, in the user's words.

    ONE class for both backends, defined here rather than in either codegen:
    every consumer of a refusal catches it by name (build.py around the
    function pipeline and around each codegen pass, comptime_runner and
    imports.py around a nested build), and a backend that defined its own
    would be a class nobody catches — so its refusals escaped as raw
    tracebacks out of `fire.py` instead of becoming the one-line diagnostic
    they are written to be. It is a shared *decision* (what counts as a
    refusal, and that both backends raise the same thing), which is what this
    module is for."""


# The value types a key element can have and still compare equal as a raw
# 64-bit word: interned string literals and integers.
CANONICAL_ELEM_TYPES = (F.IntLiteral, F.BoolLiteral, F.StringLiteral)

# ── Aggregate layout ──────────────────────────────────────────────────────
#
# A list/tuple is a blob:  [count:i64][elem0][elem1]…   (8-byte slots)
# A set lowers as a list. A dict is a PAIR blob:
#                            [count:i64][key0][val0][key1][val1]…
# A string is an interned char* with no header.
#
# The count is a PAIR count for a dict, which is why scanning one at the
# element stride only ever reaches the first half of it (slot i of a pair blob
# alternates key, value). `membership_stride` is the rule that keeps a
# membership test from making that mistake.

BLOB_HEADER_BYTES = 8      # the i64 count
ELEM_STRIDE = 8            # list element / pair slot stride
PAIR_STRIDE = 16           # key+value pair stride (also the key-address step)
VALUE_OFFSET = 8           # key -> value within a pair


def membership_stride(is_dict: bool) -> int:
    """Byte step between candidate elements of a `in` / `not in` scan.

    A dict is a pair blob, so a membership test must walk KEYS at the pair
    stride; at the element stride it would walk keys and values alternately
    and, bounded by the pair count, could only ever see half the dict."""
    return PAIR_STRIDE if is_dict else ELEM_STRIDE


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
# width]`, `size_of[type, target]`, `external_call["sym", RetType]`,
# `UnsafePointer[NoneType, MutAnyOrigin]` — or is an `__mlir_attr[...]`
# template. Those are COMPILE-TIME EXPLICIT-PARAMETER LISTS: they select an
# instantiation and hand it a type or a comptime value, and no runtime word
# corresponds to any of them.
#
# So the four readings this construct could have are settled by the source
# that uses it, and none of them is "index a flat buffer at i*stride + j":
#   * a comptime parameter list — what every corpus instance is. Lowering it
#     means resolving the parameter binding, which needs the callee's type
#     table; there is none here, and guessing a value (e.g. claiming
#     `size_of[DType.int]` is 8) would be a fabricated answer.
#   * an MLIR attribute template — what `__mlir_attr[...]` is. Not a value at
#     all on this path.
#   * a dict keyed by tuples — real, and the ONE case lowered, by the
#     element-wise key comparison above. It requires a KNOWN DICT base, which
#     only the backend knows; `multi_index_kind` takes that as an argument.
#   * a 2-D index into a flat buffer — needs a row stride. The source never
#     states one, so any stride would be invented.
#
# Therefore every non-dict case is refused, and `multi_index_refusal` says
# which of the above it is so the diagnostic names the construct rather than
# the symptom. The text is deliberately ARCH-FREE: arm64 and x86-64 return the
# same string, so the two architectures cannot drift on what a subscript means
# (see test_formal_run.py's `refuse:` cases, which assert they do not).

MULTI_INDEX_MLIR_TEMPLATE = "mlir-template"
MULTI_INDEX_COMPTIME_PARAMS = "comptime-parameters"
MULTI_INDEX_DATA = "data-multi-index"

# The MLIR spelling forms, which take a bracketed TEMPLATE rather than an
# index: the elements are backtick-quoted literal fragments interleaved with
# compile-time sub-expressions, and the whole thing denotes a dialect
# attribute. `__mlir_op` is absent on purpose — it is a real side-effecting
# op, lowered as a call (see fire_compiler's statement parser), and its
# bracket list is MLIR op attributes with `attrs` set, which is a different
# (already separately refused) node.
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


def multi_index_kind(e, base_is_dict: bool = False,
                     generic_callee=None) -> str:
    """What a multi-element subscript index means here. See the section note.

    `e` is the whole `SubscriptExpr`, so the base is available and the answer
    can be about the construct rather than about the index alone.
    `base_is_dict` is the backend's knowledge (a dict literal or a name tracked
    back to one) — the dict-keyed-by-tuples case is the only one lowered.
    `generic_callee` is the FunctionDef the base names, when the backend has
    one in hand and it is a generic; that is what separates a comptime
    parameter list from a value subscript, and it is a fact the backend can
    check rather than a guess from the spelling."""
    if base_is_dict:
        return None                       # the one lowered case; not a refusal
    if _base_name(e.obj) in MLIR_TEMPLATE_NAMES:
        return MULTI_INDEX_MLIR_TEMPLATE
    if generic_callee is not None and is_generic(generic_callee):
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


def multi_index_refusal(kind: str, spelled: str) -> str:
    """The refusal text for a multi-element subscript, identical on both paths.

    `spelled` is how the source wrote the construct, so the message points at
    something the reader can find (`size_of[type, target]`,
    `__mlir_attr[...]`, `a[i, j]`)."""
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
            "entirely on which parameters were passed. Refused rather than "
            "read as an index — a binding for `size_of[type, target]` would "
            "have to come from a target description this backend does not "
            "have, and a plausible constant is a fabricated answer."
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


def multi_index_refusal_for(e, base_is_dict: bool, callee_defs: dict = None):
    """The refusal text for `e`, or None when it is the lowered dict-key case.

    This is the ONE place either backend asks, so the two architectures
    cannot disagree about what a multi-element subscript means — the failure
    that was live at the time of writing: arm64 refused a computed tuple
    index while x86-64 used the tuple blob's own frame address as the element
    index, so `s[i, j]` segfaulted on one architecture and returned a
    different wrong answer on the other. `callee_defs` is the backend's
    `{name: FunctionDef}` table, consulted only to recognise a generic's
    explicit-parameter list; a base it does not know falls through to the
    tuple-index refusal, which is still true of it.

    Called from the address computation, not from the read: that is the one
    place a read, a store and an augmented assignment all pass through, and
    the read-only check this replaces left `a[i, j] = v` unrefused."""
    kind = multi_index_kind(e, base_is_dict=base_is_dict,
                            generic_callee=(
                                (callee_defs or {}).get(_base_name(e.obj))))
    if kind is None:
        return None
    return multi_index_refusal(kind, multi_index_spelling(e))


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


def is_generic(fn) -> bool:
    return bool(getattr(fn, "comptime_params", None))


# The kind constants live HERE, above every table that names one, because the
# string-method table below records what each method YIELDS and a table that
# had to spell "str" as a literal to dodge a forward reference would be one
# more place for the two spellings to drift apart. Their meaning is documented
# in full at the "What a value is" section further down, next to ValueKinds.
INT_KIND = "int"
STR_KIND = "str"
LIST_PREFIX = "list"


# ── Calls that are not calls to a symbol ──────────────────────────────────
#
# The default lowering of a call is a BL against a symbol spelled the way the
# source spelled it. That is right for a MODULE call (`os.path.join`, an
# imported function, a linked dylib's export) and wrong for two other things,
# both of which used to produce an image that built cleanly and then died in
# dyld with "Symbol not found" — the failure mode that is worst in a compiler,
# because everything upstream of it reports success:
#
#   * a BUILTIN whose name libSystem does not define. `print` is the one that
#     matters: it is in every hello-world-shaped file, it is not a C symbol,
#     and left to the extern path it became `BL _print`.
#   * a method call on a plain VALUE. `items.append(x)` is not a call to a
#     symbol spelled `items.append`; the receiver's VALUE picks the meaning,
#     and the receiver itself is the first argument.
#
# What each of those MEANS is a model decision, so it is here; which
# instructions implement it is the backend's.

# The methods this model can lower on a value, and what each one lowers to.
# A method NOT in this table is refused by the backend rather than guessed at:
# `elem.copy()` has no meaning without knowing what `elem` holds, and picking
# one would be a plausible-looking wrong answer behind a clean build.
#
# Membership here is NECESSARY but not SUFFICIENT: a name in it is only lowered
# when the receiver's kind is also established (see value_method_refusal), so
# adding a name here without a kind guard would lower `x.value()` on a
# non-string x as a string operation.
BUILTIN_VALUE_METHODS = {
    # `list.append(x)`: store x at count and bump the count. There is no heap
    # on this path, so the blob's capacity is a compile-time bound — the count
    # of append sites in the function — and the store is checked against it.
    "append": "list_append",
    # `f.write(s)`: a text-mode write of a C string to a file descriptor.
    # `open(...)` already lowers to the C library's `open`, so the receiver
    # IS a descriptor and this is `write(fd, s, strlen(s))`.
    "write": "file_write",
    # `f.close()`: the C library's `close` on the same descriptor.
    "close": "file_close",
}

# ── Methods on a string ───────────────────────────────────────────────────
#
# A string on this path is a bare `char *` with no header and no length: see
# the note on ValueKinds below, and bugs/FORMAL_x86_64_formal_backend_gaps.md
# for why that also makes `len` of a *string* a real question rather than a
# field load. That single fact SPLITS the string methods into two classes, and
# which side a method falls on decides whether it can be lowered at all:
#
#   POINTER-BOUNDED — the answer is a function of the bytes from the receiver
#   to the NUL, computable by walking the buffer. `strstr`/`strncmp`/`strcspn`
#   are exactly these algorithms and libSystem has all three, so the lowering
#   is a call, not a hand-written scan that could be subtly wrong.
#
#   LENGTH-DEPENDENT — the answer needs a LENGTH first, and a length on a bare
#   `char *` is only available by scanning to the NUL. Where that is the whole
#   of the work (`len`) it is still pointer-bounded, because `strlen` computes
#   it exactly. Where the length is needed to decide WHERE THE RESULT ENDS, the
#   result has to be a buffer of its own, and this path has nowhere to put one:
#   there is no heap, and the receiver's own bytes are not available as a
#   scratch area (see the strip note below).
#
# The refusal is per-NAME and says which half of that is missing, because the
# two are not interchangeable arguments: a reader who wants `split` has to
# change the string REPRESENTATION, and a reader who wants `strip` needs only
# a place to copy into.

# What each lowered string method does, and what it yields. The yield is what
# the classifier needs so that `m = s.lstrip()` binds `m` as a string and the
# NEXT method call on it is not refused for want of a kind. This is the
# `_expr_str_kind` lesson one level up: a method whose result is misclassified
# poisons every use site after it, and the symptom is a wrong answer rather
# than a diagnostic — `print(m)` prints a pointer as a number, and `m == "x"`
# compares a pointer against an integer.
POINTER_BOUNDED_METHODS = {
    # An INTERIOR pointer: the bytes from the first non-whitespace character to
    # the existing NUL are exactly the answer, still in place, and nothing is
    # written. That is what makes this one pointer-bounded and `strip` not —
    # see the strip entry in LENGTH_DEPENDENT_METHODS, which is the measured
    # reason rather than a guess.
    "lstrip": ("str_lstrip", STR_KIND),
    # `strncmp(s, p, strlen(p)) == 0` — a bounded compare, since strncmp stops
    # at the first difference or at a NUL in either operand. An empty prefix
    # is a zero-length compare, which is 0, which is "yes" as Python has it.
    "startswith": ("str_startswith", INT_KIND),
    # The same compare from the far end, but only after establishing that the
    # suffix is not longer than the receiver; without that guard the pointer
    # `s + len(s) - len(p)` is computed from an unsigned underflow and the
    # compare reads outside the buffer.
    "endswith": ("str_endswith", INT_KIND),
    # `strstr` walks to the NUL of both operands, so the index of the first
    # occurrence is exactly `strstr(s, p) - s`. An empty needle is the whole
    # receiver's start, i.e. 0, which is what Python returns.
    "find": ("str_find", INT_KIND),
    # Non-overlapping, as Python's is: each match advances the cursor by the
    # needle's length, so "aaa".count("aa") is 1 and not 2. The empty needle
    # is the one case with no loop — it matches at every position, so the
    # answer is the receiver's length.
    "count": ("str_count", INT_KIND),
}

# The ASCII whitespace set, shared by the two backends so a trim cannot mean
# one thing on arm64 and another on x86-64. 0x20 is the space; 0x09..0x0D are
# tab/LF/VT/FF/CR. As a predicate over a byte B:
#     B == 0x20  or  0x09 <= B <= 0x0D
# NUL is deliberately NOT in the set: the terminator is what ends the string,
# and trimming it would walk off the end of the buffer.
STRIP_MAX = 0x20
STRIP_LO = 0x09
STRIP_HI = 0x0D

# The same set as the ACCEPT SET of `strspn`, which is how both backends
# actually compute `lstrip`: `s + strspn(s, STRIP_CHARS)` IS the left-strip,
# because strspn returns the length of the initial segment consisting only of
# characters from that set.
#
# This is not a shortcut, it is the correction. The first version of this was a
# hand-written byte loop in each backend, and TWO bugs lived in it that neither
# shared: the arm64 copy lost the `cmp` that sets the flags its final `b.eq`
# tests, so it silently failed to trim the space — the one character the method
# is named after — while still trimming tabs; and the x86-64 copy was
# correct-looking code that did not run. One libc call is the same algorithm
# Python uses, it cannot be half-right, and there is now nothing here to keep in
# step between two architectures. A second implementation of a libc routine is
# a second thing to be wrong.
#
# The control characters are REAL bytes here, which is the point: this is a
# Python-level constant, not a Mojo string literal, so the unescaping question
# (does "\t" in the source mean a tab or a backslash and a t?) does not arise.
# STRIP_CHARS is a superset test in strspn, so a NUL in it would be a bug —
# it is not, and there is an assertion below.
STRIP_CHARS = " \t\n\v\f\r"
assert len(STRIP_CHARS) == 6, "the whitespace set changed shape"
assert "\0" not in STRIP_CHARS, "NUL must not be trimmable"
assert STRIP_CHARS[0] == chr(STRIP_MAX)
assert all(STRIP_LO <= ord(c) <= STRIP_HI for c in STRIP_CHARS[1:])

# Methods that are REAL string methods and are still refused, with the reason
# each one is out of reach. Keyed by name; the value is the missing half of
# the argument, quoted in the diagnostic.
LENGTH_DEPENDENT_METHODS = {
    # The one that is NOT about length, and the clearest statement of what is
    # actually missing. `strip` is a one-character edit away from `lstrip`:
    # both find the first non-whitespace byte. The difference is what happens
    # at the FAR end, and it is not a computation but a WRITE — a shorter
    # string has to be terminated one byte earlier, and on a bare `char *` the
    # only byte there to write is the receiver's own.
    #
    # Measured, not assumed. String literals are interned by content and
    # emitted after the code into `__TEXT,__text` (`_intern_string` in either
    # backend), and that segment is mapped `maxprot 0x5` — read and execute,
    # NO write — so writing the terminator over a literal's trailing space
    # faults. And for a receiver that is not a literal, the bytes are shared
    # with every other reference to the same interned string, so the write
    # would be visible through all of them.
    #
    # An earlier version of this lowering computed the new end pointer and
    # returned it without writing anything. It built, ran, and was WRONG:
    # "   hi   ".strip() returned a pointer to a byte that still held a space,
    # so the result printed as "   " — a plausible-looking string that is not
    # the answer. That is the outcome this table exists to prevent.
    "strip": "returns a SHORTER string, which on a bare char * means writing "
             "a terminator over the first trailing whitespace byte — and the "
             "receiver's bytes cannot be written: a string literal is interned "
             "into __TEXT,__text, which is mapped read+execute and not "
             "writable, and a non-literal receiver shares its bytes with every "
             "other reference to the same interned string. lstrip() needs no "
             "write and IS lowered",
    "rstrip": "returns a SHORTER string and so needs the terminator write that "
              "strip cannot do; see strip. lstrip() is the lowered half",
    "upper": "returns a NEW string of the same length, and the only buffer "
             "available for it is the receiver's own bytes — which live in "
             "the image's text section and are interned by content, so "
             "rewriting them in place would fault and would also change "
             "every other reference to the same literal",
    "lower": "returns a NEW string of the same length; see upper",
    "swapcase": "returns a NEW string of the same length; see upper",
    "capitalize": "returns a NEW string; see upper",
    "title": "returns a NEW string; see upper",
    "casefold": "returns a NEW string; see upper",
    "replace": "has to find every occurrence of the old text and lay the new "
               "text down between them, so the RESULT's length is not the "
               "receiver's and no buffer of the right size exists",
    "join": "has to allocate one buffer sized by walking the sequence and "
            "measuring every element, and there is no heap to allocate it in",
    "split": "returns a SEQUENCE of strings, and a sequence on this path is a "
             "frame-allocated blob whose capacity has to be a compile-time "
             "bound (the count of append sites) — a split's element count is "
             "only known at run time, so there is no capacity to give it",
    "rsplit": "returns a SEQUENCE of strings; see split",
    "splitlines": "returns a SEQUENCE of strings; see split",
    "partition": "returns a sequence; see split",
    "index": "is a length-dependent SEARCH whose result is a position, which "
             "find already answers — use find, which is lowered",
    "rfind": "walks the buffer backwards from its NUL, which needs the length "
             "first; find is the lowered direction",
    "center": "pads to a width, so it allocates a new buffer; see upper",
    "ljust": "pads to a width, so it allocates a new buffer; see upper",
    "rjust": "pads to a width, so it allocates a new buffer; see upper",
    "zfill": "pads to a width, so it allocates a new buffer; see upper",
    "format": "its result's length is a function of the format AND the "
              "operands, so it is a fresh buffer of a size nothing knows at "
              "compile time; see upper",
    "removeprefix": "returns a new string whenever the prefix is present, "
                    "which is a different pointer every time; a method that "
                    "sometimes aliases its receiver and sometimes does not is "
                    "worse than a refusal",
    "removesuffix": "returns a new string whenever the suffix is present; see "
                    "removeprefix",
    "reverse": "returns a NEW string, and writing into the receiver's own "
               "bytes would fault (see upper)",
    "__len__": "is len(), which IS lowered for a string — as strlen, not as a "
               "field read. Call len(s), which reads better and is the "
               "spelling both backends agree on",
}


def string_method_result_kind(method: str):
    """The kind a lowered string method yields, or None if it is not one."""
    entry = POINTER_BOUNDED_METHODS.get(method)
    return entry[1] if entry else None


def string_method_yields_string(call, receiver_is_str: bool) -> bool:
    """True when `call` is a lowered string method that produces a STRING.

    `receiver_is_str` is the caller's own answer to "is the receiver a char *",
    because each classifier has a different one to give: ValueKinds asks its
    own whole-function map, while a backend also has the flow-sensitive
    `_string_vars` and that one is better informed. The DECISION of what such a
    call yields belongs here so the two cannot drift — a method that one
    classifier calls a string and the other calls a word produces a program
    that is right up to the first `==` and wrong after it.

    `lstrip` is the only method this is true of today, and it is enough to
    matter: `m = s.lstrip()` followed by `m == "x"` is two statements, and
    without this the second one compares a pointer to an integer."""
    if not receiver_is_str:
        return False
    func = getattr(call, "func", None)
    if not isinstance(func, F.MemberExpr):
        return False
    return string_method_result_kind(func.member) == STR_KIND


def pointer_bounded_method(method: str):
    """The lowering name of a pointer-bounded string method, or None."""
    entry = POINTER_BOUNDED_METHODS.get(method)
    return entry[0] if entry else None


def is_string_method(method: str) -> bool:
    """True when `method` is a method of `str` in this model — whether it is
    lowered (POINTER_BOUNDED_METHODS) or refused by name
    (LENGTH_DEPENDENT_METHODS).

    The distinction matters because a name in NEITHER table is a different
    failure: the source asked for a method this model has never heard of, and
    saying "that needs a length-prefixed string" about it would be a guess
    about what it does."""
    return method in POINTER_BOUNDED_METHODS or method in LENGTH_DEPENDENT_METHODS


def value_method_refusal(method: str, receiver_kind, dotted: str) -> str | None:
    """Why `recv.method()` cannot be lowered here, or None when it can.

    Shared by both backends so the two architectures cannot disagree about
    which method calls are supported — the same rule the struct field-count
    refusal follows, and the reason this text lives in the model rather than
    being spelled twice.

    `receiver_kind` is what ValueKinds says the receiver holds, or None when
    the source does not say. It is REQUIRED for every string method and
    ignored for the container ones (`append` on a list blob, `write` on a file
    descriptor), whose meaning the receiver's name already settled.

    The kind guard is the load-bearing part. Without it, `mlir_value.value()`
    — 359 of the calls in the stdlib — would be lowered as a string operation
    on whatever word the receiver happens to hold, and a struct's `.copy()`
    would be a `strstr` over a frame address. Both build. Both are wrong."""
    if method in POINTER_BOUNDED_METHODS and method not in LENGTH_DEPENDENT_METHODS:
        if receiver_kind == STR_KIND:
            return None
        if receiver_kind is None:
            return (f"{dotted}() is a method on a string, and the source does "
                    f"not say what its receiver holds — this path has no way "
                    f"to tell a char * from a word here, and lowering "
                    f"{method!r} anyway would treat an arbitrary 64-bit word "
                    f"as a pointer to bytes. Annotate the receiver (e.g. "
                    f"`s: String`) or bind it to a string literal")
        return (f"{dotted}() is a method on a string, and its receiver is "
                f"classified as {receiver_kind!r} rather than a string. "
                f"{method!r} is only lowered on a char *, and on anything else "
                f"the same bytes mean something different")
    if method in LENGTH_DEPENDENT_METHODS:
        return (f"{dotted}() is a real method of String, but it {LENGTH_DEPENDENT_METHODS[method]}. "
                f"Answering it would need a string representation that "
                f"carries a length — a value-model change, shared by both "
                f"backends and the Lean proof, not a lowering of this one "
                f"call")
    if method in BUILTIN_VALUE_METHODS:
        return None
    return (f"{dotted}() is a method call on a value, and this backend "
            f"lowers only "
            f"{', '.join(sorted(BUILTIN_VALUE_METHODS))} and the string "
            f"methods "
            f"{', '.join(sorted(POINTER_BOUNDED_METHODS))}"
            f" — the receiver is a plain word on this path, so what "
            f"{method!r} would mean depends on what the receiver holds. "
            f"Refused rather than emitted as a call to a symbol spelled "
            f"{dotted!r}, which is what this used to do: the image built and "
            f"then died in the loader")

# The same question for a call by BARE NAME that is a builtin rather than a
# function: `open(path, "w")` is the C library's `open` underneath, but the C
# one takes an integer flags word and a bare name that is not a C symbol, so
# left to the extern path it became `BL _open` and, where a name did resolve,
# it passed the mode STRING as the flags word.
BUILTIN_FUNCTIONS = {
    "open": "file_open",
}


def builtin_function(name: str):
    """How a call to the bare name `name` lowers, or None if it is not one of
    the builtins this model represents."""
    return BUILTIN_FUNCTIONS.get(name)


# ── Where a frame ADDRESS may be handed off, and why not ───────────────────
#
# A frame address is a word, so it can be passed anywhere a word can. Whether
# that is CORRECT is a question about the callee, and the two answers are
# different enough that one message cannot cover both — which is what the single
# "which this module does not compile" diagnostic did. It is not merely
# imprecise; for the larger of the two groups it named a cause that is not
# operating, and a reader who believed it would go looking for the callee's
# field list instead of at the thing that is actually wrong.
#
#   * a BUILTIN or a C library function. It is compiled, and it is compiled as
#     an operation on a VALUE: `len(x)` reads a length out of the object, a C
#     function takes the struct's BYTES. A frame address is neither. Handing one
#     over is not a missing layout, it is a category error, and it would be a
#     wrong answer even if the callee were handed the whole struct.
#   * a function this translation unit does not compile. Here the call has
#     nowhere to go AT ALL, whatever it is passed: the image contains one file's
#     functions, so the symbol is unbound before the receiver's type is even a
#     question. Saying so first is the honest order — the layout is a real
#     second question, but it is not the one that stops this program.

# Calls by bare name that the model lowers as an operation on a value, and so
# take the VALUE rather than a pointer to it. `len` is here because it is the
# commonest one by an order of magnitude; the others are the value/type
# constructors and `origin_of`, which all ask what the object IS.
FRAME_VALUE_ONLY_CALLS = {
    "len", "origin_of", "isinstance", "issubclass", "repr", "str", "int",
    "float", "bool", "hash", "id", "type", "String", "Pointer",
    "UnsafePointer", "StringRef", "PointerType",
    # The container and scalar CONSTRUCTORS, and the folds over them.  They are
    # here for the same reason `len` is: each is lowered as an operation on the
    # value it is handed, and each is a bare name the model compiles rather than
    # a function, so without this row they fell into "this module does not
    # compile" — which for `list(x)` is false in a way a reader would have to
    # go and check.
    "list", "dict", "set", "tuple", "slice", "range", "enumerate", "zip",
    "sorted", "reversed", "sum", "min", "max", "abs", "round", "divmod",
    "chr", "ord", "hex", "oct", "bin", "any", "all",
}

# Calls by bare name that reach the C library and take the struct's storage.
FRAME_C_LIBRARY_CALLS = {
    "fcntl", "ioctl", "write", "read", "open", "close", "readv", "writev",
    "mmap", "memcpy", "memcmp", "qsort", "stat", "lstat", "fstat",
}


def frame_receiver_escape_refusal(callee: str, struct_names) -> str | None:
    """Why handing a frame ADDRESS to `callee()` is wrong, or None if it is not.

    `struct_names` is what the receiver's frame could be — one name, or several
    where the holder's type was not settled (see
    `struct_frame_slot_candidates`). The text names the struct because a
    refusal that does not is one the reader has to re-derive.

    Returns None for a callee that is one of this module's own functions: those
    take the receiver as their first parameter, which is the whole of the
    by-reference design, and their frame layout is settled at compile time. The
    CALLER decides which callees those are — it is the only side that knows
    what it compiled — so this function is about the two cases where the answer
    does not depend on that."""
    who = ", ".join(struct_names) if struct_names else "this struct"
    if callee in FRAME_VALUE_ONLY_CALLS:
        return (f"a {who} frame address is passed to {callee}(), which is "
                f"lowered as an operation on a VALUE: it wants the object "
                f"itself, and on this path a multi-field struct has no value "
                f"form — its receiver is a pointer to a frame of 8-byte slots, "
                f"so what would arrive is the address {callee}() would then "
                f"dereference as one. Not a missing layout: a wrong category "
                f"of argument. Give it a field (`{callee}(self.n)`) or copy "
                f"the value out first")
    if callee in FRAME_C_LIBRARY_CALLS:
        return (f"a {who} frame address is passed to {callee}(), which is a C "
                f"library entry point and takes the STRUCT'S BYTES by value. "
                f"The frame holds the fields at `base + 8k`, which is not the "
                f"struct's own layout, so the callee would read the wrong words "
                f"and this program would return a number the source never "
                f"wrote")
    return (f"a {who} receiver is passed to {callee}(), which this module "
            f"does not compile, so the call has nowhere to go at all: this "
            f"image contains one file's functions, and the symbol is unbound "
            f"before the receiver's layout is a question. Even with the "
            f"callee's body in hand, a frame address is only meaningful to code "
            f"compiled against the same field list, so this is refused rather "
            f"than passed. bugs/FORMAL_wide_receiver_by_reference.md records "
            f"the design and what is still open about it")


# ── The gimple backend's C runtime, by name ────────────────────────────────
#
# The OTHER backend in this repository — the one that generates GIMPLE for clang
# — has a C runtime: runtime/fire_runtime.c, embedded by every image it builds,
# with a header (runtime/fire_runtime.h, runtime/fire_sqlite3.h) that spells its
# ABI. That ABI has a naming convention of its own: every entry point is
# `mojo_<thing>`, so a program written against it calls `mojo_sqlite3_open(...)`,
# `mojo_list_len(xs)` and `mojo_print(s)` by those bare names, and
# gimple_codegen.py maps the source's own `print` onto `mojo_print` (line 617).
#
# None of that exists on a formal target. A formal image is freestanding: it
# links libSystem and nothing else (formal/build.py), it embeds no interpreter,
# and its values are one 64-bit word proved by a Lean model. So a call to one of
# these names is not an external dependency to be satisfied — it is a call into
# a library that is not part of THIS target, and the default lowering of an
# unknown bare name is a BL against a symbol spelled the way the source spelled
# it. That is the worst failure a compiler has: the build reports success and
# the program dies in the loader with "Symbol not found".
#
# So the namespace is REFUSED BY NAME here, before the extern path can reach it.
# By name rather than by shape, because the shape is not decidable: the
# repository also has ordinary Mojo functions and ordinary local variables whose
# names begin `mojo_` (scripts/stage2_mojo_interpreter.mojo defines
# `mojo_to_python` and takes a parameter called `mojo_file`), and a rule that
# could not tell those from the runtime's own entry points would refuse correct
# code. Every caller of is_gimple_runtime_builtin must therefore have already
# established that the name is NOT a function of this module and NOT an export
# of a dylib the program explicitly linked; what is left is exactly the set of
# names that reached the extern path with nowhere to bind.
GIMPLE_RUNTIME_PREFIX = "mojo_"

# The subset of the namespace whose ARGUMENT is what makes it unfixable by
# linking the library. `mojo_list_len`/`mojo_list_get_int`/`mojo_list_get_str`
# take a `MojoList *` — a heap box the gimple runtime owns, with a length and
# a data pointer inside it — while a list on a formal path is a frame blob whose
# first word IS its count (see _emit_list in either backend). So these could not
# be answered by adding libmojostdlib to the link line even in principle: the
# operand and the answer are of different types, and reading offset 0 of a
# `MojoList *` would be a plausible-looking wrong number rather than a crash.
# The refusal says so, because "no library here" is the weaker half of the
# reason and the one a reader is most likely to try to argue with.
GIMPLE_LIST_PREFIX = "mojo_list_"


def is_gimple_runtime_builtin(name: str) -> bool:
    """True when `name` is spelled as an entry point of the gimple C runtime.

    True for a call this target cannot bind, ASSUMING the caller has already
    established that the name is not a function of the module being compiled and
    not an export of a dylib the program linked. See the note above for why the
    test is a prefix and not a shape."""
    return isinstance(name, str) and name.startswith(GIMPLE_RUNTIME_PREFIX)


def gimple_runtime_refusal(name: str) -> str:
    """The refusal for a call to `name`, in the words BOTH backends must use.

    One function rather than the sentence written out in each backend, because
    the two architectures are one language implementation and a refusal that
    differed between them would be the same class of divergence as an answer
    that did (test_formal_run.py's `refuse:` cases assert the agreement)."""
    extra = ""
    if name.startswith(GIMPLE_LIST_PREFIX):
        extra = (
            " It could not be answered by linking that library either: these "
            "take a `MojoList *`, a heap box the gimple runtime owns, where a "
            "list on this path is a blob in the frame whose first word is its "
            "count — so the operand and the answer are of different types, and "
            "reading offset 0 of the box would be a plausible-looking wrong "
            "number.")
    return (
        f"{name} is an entry point of the gimple backend's C runtime (the "
        f"`{GIMPLE_RUNTIME_PREFIX}*` ABI declared in runtime/fire_runtime.h and "
        f"runtime/fire_sqlite3.h), and a formal image is freestanding: it links "
        f"libSystem and nothing else, embeds no C runtime, and its values are "
        f"one 64-bit word. There is nothing here for the call to bind to, and "
        f"nothing in it that could be lowered in the backend instead."
        f"{extra} Refused rather than emitted as a call to a symbol nothing "
        f"defines, which is what this used to do — the image built and then "
        f"died in the loader with \"Symbol not found\".")


# Python's text mode -> the C library's open(2) flag word. A formal string is a
# bare `char *`, so the mode cannot be parsed at run time; it is a decision made
# from the source, which is also the only place the information exists.
#
# The flag values are DARWIN's, and they are spelled out rather than written as
# octal literals because they are nothing like POSIX's: O_CREAT is 0x200 here
# and 0x40 on Linux, O_TRUNC is 0x400 and 0x200, O_APPEND is 0x8 and 0x400.
# Using the POSIX numbers produces calls that succeed and open the wrong thing
# (O_APPEND as O_TRUNC, O_CREAT as O_EXCL), which is worse than not compiling.
O_RDONLY = 0x0000
O_WRONLY = 0x0001
O_RDWR = 0x0002
O_APPEND = 0x0008
O_CREAT = 0x0200
O_TRUNC = 0x0400
O_EXCL = 0x0800

OPEN_WRITE = O_WRONLY | O_CREAT | O_TRUNC
OPEN_APPEND = O_WRONLY | O_CREAT | O_APPEND
OPEN_EXCLUSIVE = O_WRONLY | O_CREAT | O_EXCL

OPEN_FLAGS = {}
for _mode in ("r", "rt", "tr", "br", "rb"):
    OPEN_FLAGS[_mode] = O_RDONLY
for _mode in ("w", "wt", "tw", "bw", "wb"):
    OPEN_FLAGS[_mode] = OPEN_WRITE
for _mode in ("a", "at", "ta", "ab", "ba"):
    OPEN_FLAGS[_mode] = OPEN_APPEND
for _mode in ("x", "xt", "tx", "xb", "bx"):
    OPEN_FLAGS[_mode] = OPEN_EXCLUSIVE
# The `+` modes are the read/write ones: O_RDWR in place of O_RDONLY/O_WRONLY.
OPEN_READ_WRITE = O_RDWR
# What the file is created with when it does not exist. Python passes 0o666 and
# lets the umask take the rest; so does this.
OPEN_CRE_MODE = 0o666


def builtin_value_method(method: str):
    """How a call `recv.method(...)` lowers, or None.

    None means `method` is not a method this model represents. The caller
    distinguishes "not a value's method at all" (the receiver is a module, so
    the dotted name really is an extern) from "a method with no lowering here"
    (a refusal) by asking whether the receiver is a local value first; see
    BUILTIN_VALUE_METHODS for why the second case must not be guessed."""
    return BUILTIN_VALUE_METHODS.get(method)


# ── Calling into the C library ────────────────────────────────────────────
#
# The C library's own functions are reached as ordinary externs, bound by dyld
# through a GOT slot (see macho_linker). One of their calling conventions is not
# visible in the symbol name and has to be said here, because getting it wrong
# is a silently wrong ANSWER rather than a crash.
#
# Apple's arm64 ABI does NOT pass a variadic function's unnamed arguments in
# the argument registers. The caller builds a stack area and the i-th unnamed
# argument goes at offset 8*(i-1) from the stack pointer as it stands at the
# call; X1..X7 are ignored. A caller that does the AAPCS64-generic thing and
# puts them in registers gets a callee that reads whatever was at [sp] — which
# is how `printf("%d", 7)` on this path printed the bytes of its own format
# string. (The other half of the generic convention, AL carrying the vector
# count, does not apply here at all: clang on this target does not set it, and
# setting it corrupts X0, which on a printf call is the format pointer.)
#
# So the table records BOTH facts a call site needs: that the function is
# variadic, and how many of its arguments are NAMED (everything after them is
# `...`). Getting the second from a table rather than assuming "the first one"
# is what keeps a two-named-argument function like `fprintf(stream, fmt, ...)`
# from having its stream pointer written into the unnamed area.
VARIADIC_LIBC = {
    "printf": 1, "vprintf": 1,
    "fprintf": 2, "vfprintf": 2,
    "sprintf": 2, "vsprintf": 2,
    "snprintf": 3, "vsnprintf": 3,
    "asprintf": 1, "dprintf": 2, "vdprintf": 2,
    "syslog": 2, "err": 1, "errx": 1, "warn": 1, "warnx": 1,
    # open(2) is declared `open(const char *, int, ...)`, and Apple's build of
    # it reads the permission word from the variadic area like any other
    # variadic callee — measured, not assumed: with the word in X2 the file
    # came out with a mode made of the low bits of whatever was in that
    # register, and with it in the area the mode was 0666 & ~umask as it
    # should be.
    "open": 2,
}

# Slots the caller reserves for the unnamed arguments. The area is 8-byte
# slots like everything else on this path, and 8 of them is both the area
# Apple's own code reserves in practice and every argument register an AAPCS
# call has; a call with more is refused rather than truncated.
VARIADIC_SLOTS = 8


def variadic_named_args(symbol: str):
    """How many leading arguments of `symbol` are named, or None if it is not
    a variadic C-library function.

    Compared with the underscore stripped, because the name reaches this from
    two spellings (the source's, and the Mach-O one) and a mismatch here is
    indistinguishable from "not variadic"."""
    return VARIADIC_LIBC.get(symbol.lstrip("_"))


# ── print() ───────────────────────────────────────────────────────────────
#
# `print` writes to stdout, which is the one piece of observable behaviour a
# program cannot be said to have skipped. It is lowered, not stubbed: the
# backend builds the C format string for the call out of what each operand
# statically IS and emits a real call to the C library's `printf`, so
# `print("hello world")` puts `hello world` on stdout and the program's
# return value is still its exit status.
#
# That only works if "is this operand a string or a number" is decided before
# anything is emitted, which is the question the next section answers.

def print_literal(text: str) -> str:
    """`text` as a fragment of a `print` format string.

    Only `%` is transformed, and only because a format string is not a string:
    `print("100% done")` has to reach printf as `100%% done` or the `%` starts a
    conversion specification and the output is whatever that specification
    happened to produce.

    Everything else — newlines, tabs, quotes, backslashes — passes through
    verbatim, because the format string is not built as C SOURCE. It is a
    string-table entry: the backends append a NUL and store the bytes, and a
    literal newline byte in the table is the newline printf writes. Escaping
    here would put a backslash and an `n` on stdout instead."""
    return text.replace("%", "%%")


def print_format(fragments: list, sep: str = " ", end: str = "\n") -> str:
    """The format string for a `print` of `fragments`, in order.

    A fragment is either a conversion (`%s`, `%lld`, `%llu`) or literal text
    that has already been through `print_literal`. `sep` goes BETWEEN operands
    (never before the first, and never after the last — Python's rule, and the
    one that makes `print("a", "b")` read `a b` rather than ` a b`), and `end`
    closes the line."""
    parts = []
    for i, frag in enumerate(fragments):
        if i and sep:
            parts.append(print_literal(sep))
        parts.append(frag)
    if end:
        parts.append(print_literal(end))
    return "".join(parts)


# ── What a value is ────────────────────────────────────────────────────────
#
# A formal value is one 64-bit word. A string is a bare `char *` with no header
# and no length, so "a number" and "a string" are the SAME shape in a register
# and only the binding says which — which is why print() cannot simply format
# every operand as an integer, and why getting it wrong is invisible until the
# output is read. Deciding it must not come out differently on the two
# architectures, so the rules are here and only the register shuffling is not.
#
# Kinds:
#   "int"      an integer. On this int-only path a bool and a float are also
#              just words by the time they are values (a float literal
#              truncates toward zero on emit, per types.infer_expr), so they
#              are integers here too and print as the word they hold.
#   "str"      a `char *`.
#   "list"     a list/tuple/set blob whose element kind is not known.
#   "list:K"   such a blob known to hold only "int" or only "str" elements.
#   None       the source does not say.
#
# None is not the same as "an integer", and the difference is the whole point
# of the exercise. A NAME the source never gives an annotation or a literal
# for is a word, and a word on this path is an integer — that is the same
# default types.function_var_types already takes when it seeds every local with
# DEFAULT_INT_TYPE, and it is what makes `def f(x): print(x)` work at all,
# since almost no Mojo in the tree annotates anything. What None IS refused for
# is a CONTAINER: `print(some_list)` must not print a frame address as though
# it were the list, and a blob is the one thing a word cannot honestly stand
# for. A `char *` reaching print through an unannotated parameter is the
# remaining gap, and it is the gap the annotation exists to close; the
# diagnostic says so.
#
# Subscripting gets the string/binary distinction a different way
# (`_note_binding` tracks it per function, flow sensitively); ValueKinds is the
# same question asked of a whole function at once, for the callers that have to
# decide before any statement is emitted.

def list_kind(elem_kind):
    """The kind of a list blob whose elements are all of `elem_kind`."""
    return LIST_PREFIX if elem_kind is None else f"{LIST_PREFIX}:{elem_kind}"


def list_elem_kind(kind):
    """The element kind of a list kind, or None when it is not pinned down."""
    if not is_list_kind(kind):
        return None
    return kind.split(":", 1)[1] if ":" in kind else None


def is_list_kind(kind) -> bool:
    """True when `kind` names a list/tuple/set blob of any element kind."""
    return isinstance(kind, str) and kind.startswith(LIST_PREFIX)


def _unify(a, b):
    """The kind an expression has when its two operands have kinds `a` and `b`.

    None (undecidable) wins over a kind, and two different kinds have no
    unification at all: `x + y` is not an int because one side looks like one.
    """
    if a is None or b is None:
        return None
    if a == b:
        return a
    if a == LIST_PREFIX or b == LIST_PREFIX:
        # `+`/`|` on a blob is list concat/set union, so a list side makes the
        # whole thing a blob whatever the other side is.
        return LIST_PREFIX
    return None


def _kind_of_call(callee: str, kind_int_call) -> str | None:
    """The kind a call to `callee` produces, or None if that is not known.

    `kind_int_call` is the hook the backend uses for its own functions (a
    callee whose declared return type is an integer yields an integer); the
    builtins whose result this model fixes are decided here."""
    if callee == "len":
        return INT_KIND      # a blob's count field; len of a string is refused
    tkind = type_constructor_kind(callee)
    if tkind is not None:
        what = tkind[0]
        if what == "int":
            return INT_KIND
        if what == "identity":
            # `String(s)` is already a char *; `Pointer(p)` is a word, which
            # is not the same claim as "it is a number", so only the string
            # constructors get to say so here.
            return STR_KIND if callee in STRING_TYPE_CTORS else None
        return None
    return kind_int_call


def _kind_of_elements(elems) -> str | None:
    """The kind every element of a container literal has, or None."""
    kinds = {_kind_of_simple(el) for el in elems}
    kinds.discard(None)
    if not kinds:
        return None
    return kinds.pop() if len(kinds) == 1 else None


def _kind_of_simple(e) -> str | None:
    """The kind of an expression that needs nothing but itself to classify."""
    if isinstance(e, F.StringLiteral):
        return STR_KIND
    if isinstance(e, (F.IntLiteral, F.BoolLiteral, F.FloatLiteral)):
        return INT_KIND
    if isinstance(e, F.UnaryOp):
        if e.op == "not":
            return INT_KIND
        return _kind_of_simple(e.operand)
    return None


# The node types that are a blob whatever their contents. A name bound to one
# of these is refused rather than defaulted to a word, because the word it
# holds is an address into the frame and printing that as a number is a lie.
_CONTAINER_NODES = (F.ListExpr, F.TupleExpr, F.SetExpr, F.DictExpr,
                    F.Comprehension)


def _is_container_literal(e) -> bool:
    return isinstance(e, _CONTAINER_NODES)


class ValueKinds:
    """What the names of one function hold, decided from its source.

    Built by scanning the function's statements once (twice, so a name bound
    from a name bound later still resolves), then queried per expression while
    a call is being lowered. Deliberately flow-INsensitive: a name bound to
    two different kinds in one function is recorded as undecidable, because
    picking either one would make the answer depend on which use site asked.

    The three hooks are what a backend has to supply, and they are what makes
    this a decision rather than a lowering:
      * `int_names` / `string_names` — the type annotations that mean an
        integer and a string. A parameter's annotation is the only thing that
        says what an unassigned name holds; without one it is a word, so an
        integer (see the note on kinds above).
      * `func_kind(name)` — the kind a call to a local function produces, from
        its declared return type or, failing that, from its return statements.
      * `slot_key(member_expr)` — the local-slot key for a field chain, so a
        struct field classifies like any other name.
    """

    def __init__(self, fn, *, int_names=(), string_names=(), func_kind=None,
                 slot_key=None):
        self._int_names = frozenset(int_names)
        self._string_names = frozenset(string_names)
        self._func_kind = func_kind or (lambda name: None)
        self._slot_key = slot_key or (lambda expr: None)
        self.locals: dict = {}
        self._conflicts: set = set()
        self._returns: set = set()
        for pname, pann in _param_list(fn):
            # An unannotated parameter is a word arriving from the caller, and
            # a word is an integer here (see the note on kinds above).
            self.locals[pname] = (
                STR_KIND if pann in self._string_names else INT_KIND)
        # Two passes: a name whose value is another name bound later resolves
        # on the second. A third would not help — the chain that needs it is
        # one the first pass already walked.
        for _ in range(2):
            before = dict(self.locals)
            self._scan(getattr(fn, "body", None) or [])
            if self.locals == before:
                break
        kinds = {k for k in self._returns if k is not None}
        # A function with no `return`, or returns of more than one kind, is a
        # word: the same default an unannotated parameter gets, and for the
        # same reason.
        self.return_kind = kinds.pop() if len(kinds) == 1 else INT_KIND

    # ── scanning ───────────────────────────────────────────────────────

    def _bind(self, name, kind) -> None:
        if name in self._conflicts:
            return
        if name in self.locals:
            if self.locals[name] != kind:
                # Bound two ways in one function: refuse rather than answer
                # with whichever use site asked first.
                self.locals[name] = None
                self._conflicts.add(name)
            return
        self.locals[name] = kind

    def _bind_value(self, name, value) -> None:
        """Bind `name` to what `value` holds, defaulting an unclassified
        non-container value to a word (see the note on kinds)."""
        self._bind(name, self._value_kind(value))

    def _value_kind(self, value):
        """`kind_of(value)`, or INT_KIND when it is unclassified and is not a
        container. A list/dict/set literal, or anything already known to be a
        blob, keeps its kind: printing one of those as a number would print a
        frame address."""
        kind = self.kind_of(value)
        if kind is None and not _is_container_literal(value):
            return INT_KIND
        return kind

    def _bind_target(self, target, kind) -> None:
        """Bind whatever names an assignment target introduces."""
        if isinstance(target, F.IdentExpr):
            self._bind(target.name, kind)
        elif isinstance(target, (F.TupleExpr, F.ListExpr)):
            for el in target.elements:
                self._bind_target(el, kind)
        elif isinstance(target, str):
            for nm in _target_names(target):
                self._bind(nm, kind)

    def _scan(self, stmts) -> None:
        for s in stmts or []:
            if isinstance(s, F.AssignStmt):
                self._bind_target(s.target, self._value_kind(s.value))
            elif isinstance(s, F.VarDecl):
                self._bind_value(s.name, s.value)
            elif isinstance(s, F.AugAssignStmt):
                # `x += e` leaves x holding what it held; an unknown x stays
                # unknown rather than being called an int by the operator.
                self._bind_target(s.target, self.locals.get(
                    s.target.name if isinstance(s.target, F.IdentExpr) else ""))
            elif isinstance(s, F.MultiAssignStmt):
                for t in s.targets:
                    self._bind_target(t, self.kind_of(s.value))
            elif isinstance(s, F.ReturnStmt):
                self._returns.add(self.kind_of(s.value))
            elif isinstance(s, F.IfStmt):
                self._scan(s.then_body)
                for _c, body in (s.elifs or []):
                    self._scan(body)
                self._scan(s.else_body)
            elif isinstance(s, F.WhileStmt):
                self._scan(s.body)
                self._scan(s.else_body)
            elif isinstance(s, F.ForStmt):
                self._bind_target(s.target, self._iterable_kind(s.iterable))
                self._scan(s.body)
                self._scan(s.else_body)
            elif isinstance(s, F.WithStmt):
                for it in (s.items or []):
                    if getattr(it, "alias", None) is not None:
                        self._bind(str(it.alias), self.kind_of(it.expr))
                self._scan(s.body)
            elif isinstance(s, F.TryStmt):
                self._scan(s.body)
                for h in (s.handlers or []):
                    self._scan(h.body)
                self._scan(s.else_body)
                self._scan(s.finally_body)
            elif isinstance(s, F.FunctionDef):
                # A nested def has its own locals, and its own return type; do
                # not let its names leak into this function's map.
                self._bind(s.name, self._return_kind(s))

    def _iterable_kind(self, iterable):
        """What a `for`/`in` binds from `iterable`.

        A container literal knows its own element kind; `range` yields
        integers; anything else is a blob whose elements this path treats as
        words (types.function_var_types says the same about loop variables)."""
        if isinstance(iterable, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            return list_kind(_kind_of_elements(iterable.elements))
        if isinstance(iterable, F.Comprehension):
            return list_kind(_kind_of_simple(iterable.element))
        if isinstance(iterable, F.CallExpr) and _flat_callee(iterable) == "range":
            return INT_KIND
        return INT_KIND

    def _return_kind(self, fn) -> str | None:
        ann = getattr(fn, "return_type", None)
        if ann in self._int_names:
            return INT_KIND
        if ann in self._string_names:
            return STR_KIND
        return None

    # ── querying ───────────────────────────────────────────────────────

    def name_kind(self, name: str):
        """What the local `name` holds, or None if this does not say."""
        if name in self._conflicts:
            return None
        return self.locals.get(name)

    def kind_of(self, e):
        """What `e` evaluates to, or None when the source does not say."""
        k = _kind_of_simple(e)
        if k is not None or isinstance(e, (F.StringLiteral, F.IntLiteral,
                                           F.BoolLiteral, F.FloatLiteral)):
            return k
        if isinstance(e, F.IdentExpr):
            return self.name_kind(e.name)
        if isinstance(e, F.MemberExpr):
            key = self._slot_key(e)
            return self.name_kind(key) if key is not None else None
        if isinstance(e, F.UnaryOp):
            if e.op in ("*", "**"):
                return None              # *args / **kwargs have no single kind
            return self.kind_of(e.operand)
        if isinstance(e, F.BinaryOp):
            if e.op in _COMPARISON_OPS or e.op in ("and", "or"):
                return INT_KIND          # a comparison or a bool is 0/1
            return _unify(self.kind_of(e.left), self.kind_of(e.right))
        if isinstance(e, F.CompareChain):
            return INT_KIND
        if isinstance(e, F.TernaryExpr):
            # `then_val` / `else_val`, not `body` / `orelse`: `F.TernaryExpr`
            # (fire_compiler.py:309) has no `body` and no `orelse`, so this line
            # raised `AttributeError` on every ternary it was ever handed.  It
            # was unreachable until the frame pass stopped refusing a handful of
            # files ahead of the codegen, and then twenty of them landed in
            # `backend-crash` — a worse verdict than the refusal that used to
            # hide it, and one this file's own arithmetic is what turned them
            # into.  The kind of a ternary is the join of its two arms, and
            # `_unify` is the same join every other two-armed form above uses.
            return _unify(self.kind_of(e.then_val), self.kind_of(e.else_val))
        if isinstance(e, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            return list_kind(_kind_of_elements(e.elements))
        if isinstance(e, F.DictExpr):
            return LIST_PREFIX
        if isinstance(e, F.Comprehension):
            if e.kind == "dict":
                return LIST_PREFIX
            ek = _kind_of_simple(e.element)
            if e.key is not None:
                ek = _unify(ek, _kind_of_simple(e.key))
            return list_kind(ek)
        if isinstance(e, F.CallExpr):
            callee = _flat_callee(e)
            if callee is None:
                return None
            # A lowered string method, asked first: `m = s.strip()` binds `m`,
            # and if `m` came back as a word then the NEXT method call on it
            # would be refused for want of a kind and a correct program would
            # stop. The receiver's own kind is the condition, for the same
            # reason the backend guards the lowering on it.
            skind = self._string_method_kind(e)
            if skind is not None:
                return skind
            kind = _kind_of_call(callee, self._func_kind(callee))
            if kind is not None:
                return kind
            if (self._func_kind(callee) is not None
                    or type_constructor_kind(callee) is not None):
                # A function of this module, or a type constructor: something
                # here said it cannot be a plain word, and that answer stands.
                return None
            # An EXTERN — a C library function, an imported one, a helper from
            # a library this program links. Whatever it returns is a word, the
            # same default an unannotated parameter gets, and saying so keeps
            # `print(errmsg(db))` a formatting question rather than a refusal
            # about a function the module never declared.
            return INT_KIND
        if isinstance(e, F.SubscriptExpr):
            if not isinstance(e.index, F.SliceExpr):
                return list_elem_kind(self.kind_of(e.obj))
        return None

    def _string_method_kind(self, call):
        """What a lowered string method call yields, or None if this is not one.

        None for a method the model does not lower, for a bare name, and — the
        case that makes this a guard rather than a lookup — for a method whose
        receiver is not classified as a string. `x.value()` on a struct whose
        kind is unknown must stay unknown here, or the caller would bind `x`'s
        result to a string and format an integer as text."""
        func = call.func
        if not isinstance(func, F.MemberExpr):
            return None
        method = func.member
        if method not in POINTER_BOUNDED_METHODS:
            return None
        if not string_method_yields_string(call, self.kind_of(func.obj) == STR_KIND):
            return None
        return POINTER_BOUNDED_METHODS[method][1]


_COMPARISON_OPS = ("<", ">", "<=", ">=", "==", "!=", "is", "is not", "in",
                   "not in")


def _flat_callee(call) -> str | None:
    """The dotted name a call's callee spells, or None if it is not a name.

    A module call (`os.path.join`) and a value's method (`items.append`) both
    arrive as a dotted name; the backends tell them apart by asking whether the
    receiver is a local, not by looking at the spelling."""
    func = call.func if isinstance(call, F.CallExpr) else call
    if isinstance(func, F.IdentExpr):
        return func.name
    parts = []
    node = func
    while isinstance(node, F.MemberExpr):
        parts.append(node.member)
        node = node.obj
    if parts and isinstance(node, F.IdentExpr):
        parts.append(node.name)
        return ".".join(reversed(parts))
    return None


def _param_list(fn):
    return list(getattr(fn, "params", None) or [])


def _target_names(target):
    from mojo.middle.boundnames import _lbn_target_names
    return _lbn_target_names(target) if isinstance(target, str) else []


# ── Constructs that are no-ops in the value flow ──────────────────────────
#
# These name source constructs whose only meaning is to the compiler, so a
# backend can pass the operand/value straight through. They are no-ops in
# BOTH senses: nothing is computed, and nothing is lost.


def is_ownership_transfer(node) -> bool:
    """`x^` — Mojo's ownership transfer marker.

    A borrow-check annotation naming no runtime operation, so the value flows
    through unchanged. The gimple path makes the same call on its unary
    lowering ("Ownership transfer operator (^) - just pass the value through",
    mojo/backend_gimple/emit_exprs.py). Refusing it instead would reject every
    stdlib module that moves a value."""
    return (getattr(node, "op", None) == "^"
            and type(node).__name__ == "UnaryOp")


def is_ellipsis(node) -> bool:
    """A bare `...` — a declaration with no body, or a placeholder value.

    Emits nothing and yields 0, the same "nothing here" a None literal gets."""
    return type(node).__name__ == "EllipsisLiteral"


# ── Type constructors ─────────────────────────────────────────────────────
#
# `Int(x)`, `Int32(x)`, `String(s)` are CONVERSIONS, not calls: a value in this
# model is a 64-bit word, so constructing an integer type means normalizing the
# operand to that type's width and signedness, and a string is already a
# `char *`. Without this they lower to a BL against a symbol named `Int` — an
# extern nothing defines, so the image builds and then dies in dyld. That made
# `Int`, `String` and `Int32` the most common unresolvable imports in the
# stdlib, which is a self-inflicted wound rather than a linking requirement.
#
# The DECISION is here; the width normalization is the backend's (it owns the
# sign/zero-extend instructions). A container type (`List`, `Dict`, `SIMD`) has
# no representation on this path at all and is NOT in the table, so it stays an
# honest "unsupported" rather than a silent zero.

# Integer type constructors -> their width/signedness. Mirrors
# formal.types.TYPE_NAMES, which is the authority; this is the subset that is
# meaningful as a *value* conversion.
INT_TYPE_CTORS = {
    "int": (64, False), "Int": (64, True),
    "Int8": (8, True), "Int16": (16, True),
    "Int32": (32, True), "Int64": (64, True),
    "UInt8": (8, False), "UInt16": (16, False),
    "UInt32": (32, False), "UInt64": (64, False),
}

# Types whose construction is the identity on this path: a string already IS a
# `char *`, and a pointer is already a word, so constructing one is a no-op.
IDENTITY_TYPE_CTORS = ("String", "str", "StringLiteral", "StringSlice",
                       "Pointer", "UnsafePointer", "CPointer")

# The subset of those that produce a STRING rather than an opaque word. Kept as
# a name of its own because `String(s)` is a char * — which is a fact a caller
# can act on (print formats it with %s) — while `Pointer(p)` is a word, and
# treating the two alike would mean handing printf an address to dereference.
# The same list as formal.types.STRING_TYPE_NAMES, named here so this module
# does not have to import types to say it.
STRING_TYPE_CTORS = ("String", "str", "StringLiteral", "StringSlice")

# Type names that are real types with NO representation on this path. Calling
# one used to emit a BL against a symbol named e.g. `Error` — an extern nothing
# defines, so the image built and then died in dyld. Naming them here turns
# that into the honest refusal this path prefers: a fat pointer (`Span`), a
# struct (`Error`) or a vector (`SIMD`) cannot be conjured out of one word, and
# saying so beats emitting a call that cannot be linked.
UNREPRESENTABLE_TYPE_CTORS = (
    "Span", "Error", "SIMD", "SIMDVector", "List", "Dict", "Set", "Tuple",
    "Optional", "StringRef", "DType", "InlineArray", "Array", "StaticTuple",
)


def type_constructor_kind(callee_name: str):
    """How to lower a call whose callee is the bare name `callee_name`, or None.

    'int' -> (width, signed): normalize the single operand to that type.
    'identity' -> pass the single operand through.
    'unsupported' -> a real type this path cannot represent; the backend turns
    that into a clear error rather than a dangling extern.
    None -> not a type constructor at all (a genuine function call)."""
    if callee_name in INT_TYPE_CTORS:
        return ("int", INT_TYPE_CTORS[callee_name])
    if callee_name in IDENTITY_TYPE_CTORS:
        return ("identity", None)
    if callee_name in UNREPRESENTABLE_TYPE_CTORS:
        return ("unsupported", None)
    return None


# ── Operator surface ──────────────────────────────────────────────────────
#
# Which augmented operators the formal paths lower at all. The SET is a
# platform/language decision; the mapping from operator to instruction is the
# backend's.

AUG_OPS = ("+", "-", "*", "/", "//", "%", "&", "|", "^", "<<", ">>", "**")
AUG_SHIFT_OPS = ("<<", ">>")
AUG_DIV_OPS = ("/", "//", "%")     # need the divide-by-zero exit, not a plain ALU


# ── structs ──────────────────────────────────────────────────────────────
# A formal value is ONE 64-bit word. A struct is representable exactly when
# its fields fit that word, which makes the field count the whole of the
# decision — there is no partial layout to attempt, and a struct that does not
# fit is refused by name and width rather than miscompiled. These predicates
# are shared because the answer must not differ between the backends that
# share this model.

def struct_fields(struct_def) -> list:
    return list(getattr(struct_def, "fields", None) or [])


def struct_field_name(field) -> object:
    """The name this one `StructDef` field introduces, or None if it has none.

    A field arrives in either of the two shapes fire_compiler's parser puts in
    `StructDef.fields` — everything in a struct body that is a `VarDecl` or an
    `AssignStmt` is a field, because a class-level assignment IS a field with a
    default on this path:

      * `VarDecl` — written as an annotation, `x: int` (or `x: int = 0`, which
        the parser keeps as an `AssignStmt` carrying `type_ann`); the name is
        `field.name`.
      * `AssignStmt` — written as a plain class-level assignment, `x = 1` or
        `__slots__ = (...)`; the name is `field.target.name`.

    So the two shapes carry the name in different places, and every reader has
    to ask here. Reaching for `.name` directly works for the first and raises
    `AttributeError` on the second, which is how `__slots__ = (...)` in a
    one-field struct used to abort a build with a Python traceback instead of a
    diagnostic. None means the field binds no name at all (a class-level
    `obj.attr = 1`); callers that need a name must treat that as a real error
    rather than guess one."""
    if isinstance(field, F.VarDecl):
        return field.name
    if isinstance(field, F.AssignStmt) and isinstance(field.target, F.IdentExpr):
        return field.target.name
    return None


# The class-level assignment that DECLARES fields rather than making one, and
# the two names a `__slots__` tuple may carry that are not storage at all
# (Python adds them itself to a class that wants weak references or a
# `__dict__`). Counting either would make a one-field `__slots__` class look
# like a two- or three-field one, i.e. refuse a struct that is representable.
SLOTS_FIELD = "__slots__"
_PSEUDO_SLOTS = ("__dict__", "__weakref__")


def _slots_names(value) -> list:
    """The field names a `__slots__ = (...)` value declares; [] if it is not one.

    `__slots__` is the one class-level assignment that is a declaration rather
    than a definition: it names fields instead of storing into one, and it is
    the only place a class can name a field it never assigns. Reading it is
    what keeps `__slots__ = ("it",)` in a class whose `__init__` does
    `self.it = ...` from being counted as two fields (`it` and `__slots__`)
    rather than the one field it is."""
    if not isinstance(value, (F.TupleExpr, F.ListExpr)):
        return []
    out = []
    for el in getattr(value, "elements", None) or []:
        if isinstance(el, F.StringLiteral) and isinstance(el.value, str) \
                and el.value not in _PSEUDO_SLOTS:
            out.append(el.value)
    return out


def _self_field_names(node, out: set, receivers=("self",)) -> None:
    """Add to `out` every name reached as `<receiver>.<name>` under `node`.

    A field access either way round declares a field: `self.x = 1` writes one,
    and a bare `self.x` reads one that some other method (or the caller) filled
    in. A Python class that only ever READS a field declares it just as really
    as one that assigns it, and a width computed from the assignments alone
    would call such a class a zero-field marker and then compile a read of
    storage that nothing ever wrote.

    A method call is not a field access. `self.helper()` names a method, and
    counting it would add a field to every class that calls one of its own
    methods — enough to make a genuinely one-word class measure wide. So a
    `CallExpr` whose callee is `<receiver>.<name>` contributes nothing and its
    callee is not descended into, while its arguments still are (a method can
    be handed `self.x` as an argument, which is a real field access).

    A nested `FunctionDef` is not descended into either: its `self`, if it has
    one, is a different binding from the struct's receiver.

    `receivers` is every spelling this struct's own methods bind their receiver
    to — `self` plus each method's first parameter (see `struct_receivers`).
    It was `self` alone, which missed a class written `def __init__(this)` or a
    `@classmethod def is_float(cls, …)`: their `this.n` / `cls._SIGNED` were
    invisible here, so a field written only that way looked unwritten. Missing
    a field is the direction that aliases two real fields into one slot, so the
    receiver set is a superset of the obvious spelling rather than just it."""
    if isinstance(node, list):
        for x in node:
            _self_field_names(x, out, receivers)
        return
    if isinstance(node, F.FunctionDef):
        return
    if isinstance(node, F.CallExpr) and isinstance(node.func, F.MemberExpr) \
            and isinstance(node.func.obj, F.IdentExpr) \
            and node.func.obj.name in receivers:
        for a in node.args or []:
            _self_field_names(a, out, receivers)
        for _k, v in (node.kwargs or []):
            _self_field_names(v, out, receivers)
        return
    if isinstance(node, F.MemberExpr) and isinstance(node.obj, F.IdentExpr) \
            and node.obj.name in receivers:
        out.add(node.member)
        return
    for fname in getattr(node, "__dataclass_fields__", {}):
        if fname in ("line", "col"):
            continue
        _self_field_names(getattr(node, fname, None), out, receivers)


def _decorator_names(method) -> set:
    """The decorator names on a method, as bare strings.

    `@staticmethod` / `@classmethod` are spelled bare in the source and arrive
    as the string; a call form (`@functools.wraps(f)`) arrives as a CallExpr
    and contributes only its callee, which is enough to keep it from matching
    the two names that matter here."""
    out = set()
    for d in getattr(method, "decorators", None) or []:
        if isinstance(d, str):
            out.add(d)
        elif isinstance(d, F.IdentExpr):
            out.add(d.name)
        elif isinstance(d, F.CallExpr) and isinstance(d.func, F.IdentExpr):
            out.add(d.func.name)
    return out


def struct_receivers(struct_def) -> set:
    """Every name this struct's own methods bind their receiver to.

    `self` — the overwhelmingly common spelling — plus the first parameter of
    every method that HAS a receiver, which is the same binding written
    differently: `def __init__(this)` stores into `this.n`, and a
    `@classmethod def is_float(cls, …)` reads the class through `cls`. Both are
    real member accesses, and a receiver set that recognised only the literal
    `self` could not see them, so a field written only that way looked
    unwritten — and a field that looks unwritten is the one error this whole
    rule is built to avoid.

    A `@staticmethod`'s first parameter is NOT a receiver; it is an ordinary
    argument, and treating it as one made `myinterpreter.Interpreter` measure 34
    fields instead of 10 (every `node.<attr>` an `@staticmethod` helper read
    became a field of the class it happened to live in). That is the safe
    direction and a useless one — a census that calls an argument a field stops
    being a census — so the decorator decides, and an unrecognised decorator
    form is treated as HAVING a receiver."""
    out = {"self"}
    for m in struct_methods(struct_def):
        if "staticmethod" in _decorator_names(m):
            continue
        params = list(getattr(m, "params", None) or [])
        if params and isinstance(params[0], (tuple, list)) and params[0]:
            first = params[0][0]
            if isinstance(first, str):
                out.add(first)
    return out


def struct_declared_names(struct_def) -> list:
    """The class body's own names, in declaration order, `__slots__` expanded.

    The `fields` list minus the `__slots__` bookkeeping, kept as a function
    because the demotion rule below needs the ORDER (a positional constructor
    fills fields in declaration order) and because `struct_field_names` needs
    the same list without recomputing it."""
    out, seen = [], set()
    for field in struct_fields(struct_def):
        slots = _slots_names(field.value) \
            if isinstance(field, F.AssignStmt) \
            and struct_field_name(field) == SLOTS_FIELD else []
        for name in (slots or [struct_field_name(field)]):
            if isinstance(name, str) and name not in seen:
                seen.add(name)
                out.append(name)
    return out


# ── Telling a class-level CONSTANT from per-instance state ───────────────
#
# `struct_field_names` counts a class-level assignment as a field, because it
# has no type information and cannot tell `x = 1` (a constant every instance
# shares) from `x: int` (a slot per instance). Counting both is the safe
# direction — a constant counted as a field can only cause a refusal, never a
# wrong answer — and for a long time it was also the ONLY direction. The
# conservative direction is only free while it costs nothing, and here it cost
# the whole arm64 sweep's headline number: `GimpleGen` was reported as a
# 263-field receiver whose first fields were `BUILTIN_VALUE_MAP,
# _KNOWN_EXCEPTION_NAMES, _KNOWN_SIGS`, i.e. the diagnostic led with its lookup
# tables, and 15 of the 263 were not fields at all.
#
# So the rule is a real one, derived from the whole translation unit rather
# than from the class body, and it is deliberately lopsided: EVERY doubt
# resolves to "field". Naming an instance field a constant is the catastrophic
# error on this path — the receiver is then treated as narrower than it is, two
# real fields collapse into one slot, and the program builds, runs, and returns
# the wrong number. Naming a constant a field is a refusal with a good message.
# Nothing below may resolve a doubt the other way.
#
# The rule: a class-level name is a CONSTANT — not per-instance state — when
# every one of these holds.
#
#   1. It is declared in the class body and NOT named by `__slots__`.
#      `__slots__` is a declaration of instance storage in the language itself,
#      so a name it lists is a field whatever else is true of it.
#   2. No method of this struct reaches it through the receiver (`self.NAME`,
#      `this.NAME`, `cls.NAME` — see struct_receivers). A read through the
#      receiver is what the member-access lowering turns into a local slot
#      spelled `self.<name>`, and nothing here can prove such a slot is not
#      this struct's own storage, so it stays a field.
#      This one is not only conservative, it is what makes the `self.CONST`
#      spelling CORRECT: a one-field struct's receiver IS its field, so
#      `return self.A` with `A = 3` reads the word `A()` left there, and
#      `struct_default_word` is what put the 3 there. Demote `A` instead and
#      the read falls to a slot nothing ever writes, which is 0 — so the
#      materializing rewrite in formal/build.py would have to reach the
#      receiver spelling too. Keeping the name a field gets it right for free,
#      and the existing `struct_default_word_int` case is that program.
#   3. Nothing in the translation unit WRITES it through any object —
#      `obj.NAME = …`, `obj.NAME += …`, `for obj.NAME in …`, `del obj.NAME`
#      (see `unit_field_evidence`). This is the load-bearing clause, and the
#      reason the rule is sound: on this path a field that is never written
#      through a receiver can only ever READ as the same value in every
#      instance (an unwritten local slot, which is 0), so it carries no
#      per-instance state to lose. A class that merely NAMES a field without
#      writing it is clause 6's business, not this one's.
#   4. Nothing in the translation unit fills it by NAME — a keyword argument
#      (`Point(x=1)`) or a positional argument to this struct's constructor
#      (which fills declared fields in declaration order). A dataclass whose
#      fields are all set in its own constructor is full of names that clause 3
#      alone would demote, and demoting them is precisely the aliasing bug:
#      `Point(x=1, y=2)` writes two fields that no `obj.x` ever appears to.
#   5. The unit has no name-less attribute write this census cannot see —
#      `setattr(o, name, v)` with a computed name, a `__dict__` subscript with
#      a computed key, `globals()[…] = …`. Then NO name in the unit is demoted
#      (see the `dynamic` flag), because a write nobody can name is a write to
#      everything.
#   6. It is declared WITH a value. `LIMIT = 10` defines a value every instance
#      shares; `var limit: Int` declares storage and nothing else. The second
#      is a field even when no code in the unit ever writes it, because the
#      moment anything reads one of two such fields they would share a word —
#      and `struct Pair: var a: Int; var b: Int` is refused by name for exactly
#      that reason (test_formal_imports.py asserts it). A declaration with no
#      initializer is the one shape in which "nothing writes it" is a statement
#      about the PROGRAM rather than about the DECLARATION.
#
# Two things this deliberately does NOT do. It does not resolve a bare read:
# `X` inside a method does not see the class body's scope in Python or Mojo, so
# a bare read is a global (or a local), never this rule's constant — there is
# nothing here to decide. And it does not demote on a name's NAME, however
# constant-looking (`_SIGNED = 1` and `self.n = 0` differ in spelling and in
# nothing else a typeless scan can see); it decides on where the name is
# WRITTEN, which is the one property that separates the two.
#
# What it is worth, measured: of 232 structs in the repository 11 get narrower,
# by exactly the names the rule identifies, and NONE gets wider. What it does
# NOT buy is a receiver that has real instance state: `GimpleGen` has 248 of
# those, so the sixteen files refused on it are still refused, and the honest
# summary of that half is in the sweep's own numbers rather than here.

# The name-less attribute writers, and what to do about each. `setattr` and
# `delattr` with a string LITERAL name are readable, and the name is added to
# the evidence; with a computed name they are not, so the whole unit is treated
# as dynamic. `globals`/`locals`/`vars`/`eval`/`exec` can manufacture a write
# out of nothing and are therefore dynamic outright.
_DYNAMIC_WRITERS = ("globals", "locals", "vars", "eval", "exec")
_STRING_NAMED_WRITERS = ("setattr", "delattr")
# `o.__dict__` / `o.__dict__[k]` / `o.__dict__.update(...)` — a dict of
# attributes under a name this scan can read, so it is decoded rather than
# distrusted; a computed key is not decodable and is dynamic.
_DICT_CHAIN_METHODS = ("update", "setdefault", "pop")


def _dict_chain_key(node):
    """What a `__dict__` read or write names: an attribute name, "" or None.

    An attribute name for `o.__dict__["n"]` and for `.update`/`.setdefault`/
    `.pop` called on a `__dict__` with a string literal; "" for a node that has
    nothing to do with `__dict__` at all (which is nearly every subscript in the
    repository — `d[k]`, `a[i]` — and must not be confused with one that does);
    None for a `__dict__` chain whose key is computed, which is the one thing
    here the caller cannot resolve, so it turns the whole unit dynamic."""
    if isinstance(node, F.SubscriptExpr):
        if not _rooted_at(node.obj, "__dict__"):
            return ""
        idx = node.index
        if isinstance(idx, F.StringLiteral) and isinstance(idx.value, str):
            return idx.value
        return None
    if isinstance(node, F.CallExpr) and isinstance(node.func, F.MemberExpr) \
            and node.func.member in _DICT_CHAIN_METHODS:
        if not _rooted_at(node.func.obj, "__dict__"):
            return ""
        for a in list(node.args) + [v for _k, v in (node.kwargs or [])]:
            if isinstance(a, F.StringLiteral) and isinstance(a.value, str):
                return a.value
        return None
    return ""


def _rooted_at(node, member: str) -> bool:
    """True when `node` is `….<member>` or a subscript/attribute chain on one."""
    while True:
        if isinstance(node, F.MemberExpr):
            if node.member == member:
                return True
            node = node.obj
            continue
        if isinstance(node, F.SubscriptExpr):
            node = node.obj
            continue
        return False


def unit_field_evidence(stmts) -> tuple:
    """`(names, dynamic)` — what one translation unit says about instance state.

    `names` is every name this unit could possibly write into a field, by any
    spelling that carries the name: a member-assignment target, a
    keyword-argument name, a string literal handed to `setattr`/`delattr`/
    `__dict__`, and — for a call to a struct declared in the same unit — each
    positional argument, which fills that struct's declared fields in
    declaration order.

    `dynamic` is True when the unit contains a write whose NAME this scan
    cannot read. It is a blunt instrument on purpose: one `setattr(o, k, v)`
    with a computed `k` means no name in the unit can be trusted as unwritten,
    and the cost of being wrong in that direction is a silent wrong answer
    rather than a refusal."""
    declared = {}
    for st in iter_struct_defs(stmts):
        names = struct_declared_names(st)
        if names:
            declared[getattr(st, "name", None)] = names
    names, dynamic = set(), False

    def walk(node):
        nonlocal dynamic
        if isinstance(node, list):
            for x in node:
                walk(x)
            return
        if not hasattr(node, "__dataclass_fields__"):
            return
        # a member in ASSIGNMENT position — the only write that makes a field
        # per-instance state. `targets` covers MultiAssignStmt and DelStmt,
        # which is where `a, b.x = …` and `del b.x` land.
        for tgt in [getattr(node, "target", None)] \
                + list(getattr(node, "targets", None) or []):
            if isinstance(tgt, F.MemberExpr):
                names.add(tgt.member)
        if isinstance(node, F.CallExpr):
            for k, _v in (node.kwargs or []):
                if isinstance(k, str):
                    names.add(k)
            callee = node.func
            if isinstance(callee, F.IdentExpr):
                if callee.name in _DYNAMIC_WRITERS:
                    dynamic = True
                elif callee.name in _STRING_NAMED_WRITERS:
                    if len(node.args) >= 2 and isinstance(node.args[1],
                                                          F.StringLiteral) \
                            and isinstance(node.args[1].value, str):
                        names.add(node.args[1].value)
                    else:
                        dynamic = True
                else:
                    for i, _a in enumerate(node.args or []):
                        if i < len(declared.get(callee.name, ())):
                            names.add(declared[callee.name][i])
        key = _dict_chain_key(node)
        if key is None:
            dynamic = True
        elif key:
            names.add(key)
        for fname in node.__dataclass_fields__:
            if fname in ("line", "col"):
                continue
            walk(getattr(node, fname, None))

    walk(stmts)
    return (frozenset(names), dynamic)


def struct_field_evidence(struct_def):
    """The `(names, dynamic)` evidence attached to this struct, or None.

    None means NO evidence — not "no evidence against". A struct nobody
    attached evidence to keeps every class-level name as a field, which is
    exactly the pre-rule behaviour; that is what a caller that cannot see the
    whole unit gets, and it is why attaching it is the pipeline's job rather
    than an optimisation."""
    return getattr(struct_def, "_field_evidence", None)


def attach_field_evidence(struct_defs, evidence) -> None:
    """Give every one of `struct_defs` this evidence, in place.

    On the struct rather than passed down, because the two backends ask the
    model about a struct they were handed, with no unit in hand: a width that
    depended on a caller-supplied argument could differ between the build pass
    and the codegen pass, which is the one divergence this shared model exists
    to make impossible (see this module's docstring)."""
    for st in struct_defs or []:
        setattr(st, "_field_evidence", evidence)


def iter_struct_defs(node):
    """Every StructDef under `node`, including nested ones.

    Public because the build pipeline needs the same set the census is taken
    over (`parse_module` attaches the evidence, `_prepare_functions` re-attaches
    it to the structs the file being compiled declares), and a second,
    slightly different notion of "the structs in this statement list" is how one
    of the two ends up measuring a class the other does not."""
    if isinstance(node, list):
        for x in node:
            yield from iter_struct_defs(x)
        return
    if not hasattr(node, "__dataclass_fields__"):
        return
    if isinstance(node, F.StructDef):
        yield node
    for fname in node.__dataclass_fields__:
        if fname in ("line", "col"):
            continue
        yield from iter_struct_defs(getattr(node, fname, None))


def _split_declaration(struct_def):
    """`(fields, constants)` — the two halves of the class body, or None.

    None means "no evidence", i.e. the caller must fall back to counting every
    declared name as a field; see `struct_field_evidence` for why that is the
    answer rather than "no constants".

    `constants` is `[(name, default_node)]` in declaration order, which is also
    the order a positional constructor fills them in, so it is kept rather than
    reduced to a set."""
    evidence = struct_field_evidence(struct_def)
    if evidence is None:
        return None
    written, dynamic = evidence
    receivers = struct_receivers(struct_def)
    # clause 2, over the whole struct: every name any of its own methods
    # reaches through the receiver, whatever the unit-wide write census says.
    reached = set()
    for method in struct_methods(struct_def):
        _self_field_names(getattr(method, "body", None), reached, receivers)
    fields, constants, seen = [], [], set()
    for field in struct_fields(struct_def):
        slots = _slots_names(field.value) \
            if isinstance(field, F.AssignStmt) \
            and struct_field_name(field) == SLOTS_FIELD else []
        for name in (slots or [struct_field_name(field)]):
            if not isinstance(name, str) or name in seen:
                continue
            seen.add(name)
            # clause 1: a `__slots__` name is instance storage by declaration.
            # clause 3/4: written anywhere in the unit, by receiver or by name.
            # clause 5: nothing is demoted while the unit has a write whose
            # name cannot be read, so `dynamic` short-circuits all of it.
            through = reached | _receiver_names(getattr(field, "value", None),
                                                receivers)
            if slots or dynamic or name in written or name in through \
                    or getattr(field, "value", None) is None:
                # clause 6, and the reason a DECLARED field is not a constant:
                # a class-level name with no initializer (`var a: Int`) declares
                # storage, while one WITH a value (`_SIGNED = 1`) defines a
                # value every instance shares. `struct Pair: var a: Int; var b:
                # Int` is a two-field struct even in a program that never
                # touches either field, and refusing it is what
                # test_formal_imports.py's `a struct too wide for one word is
                # refused by name` asserts; demoting it would make the two
                # fields share one word the moment anything read them.
                fields.append(name)
            else:
                constants.append((name, getattr(field, "value", None)))
    # Per method, not globally sorted, so that the field list is byte-for-byte
    # the list `_pre_rule_field_names` produces for a struct with no evidence:
    # a name that moves position in a diagnostic is a change nobody asked for.
    for method in struct_methods(struct_def):
        touched = _receiver_names(getattr(method, "body", None), receivers)
        for name in sorted(touched):
            if name not in seen:
                seen.add(name)
                fields.append(name)
    return (fields, constants)


def _receiver_names(node, receivers) -> set:
    """The names `node` reaches through one of `receivers`."""
    out = set()
    _self_field_names(node, out, receivers)
    return out


def struct_class_constants(struct_def) -> list:
    """`(name, default_node)` per class-level constant, in declaration order.

    The complement of `struct_field_names`, and empty for every struct with no
    evidence attached — where nothing can be told apart, so everything stays a
    field and there is no constant to speak of."""
    split = _split_declaration(struct_def)
    return list(split[1]) if split is not None else []


def struct_field_names(struct_def) -> list:
    """Every INSTANCE field name this struct has, in a stable order.

    THE field set, and therefore the whole of the representability decision
    (`struct_fits_one_word` reads its length). It is derived from every place a
    field can be introduced rather than from the class body alone, because the
    class body alone is not where most of this repo's own classes put their
    fields:

      * a class-level `VarDecl` / assignment — the annotated or defaulted
        spelling (`x: int`, `x: int = 0`, `x = 0`) — MINUS the names that are
        class-level CONSTANTS rather than storage, which is what
        `struct_class_constants` decides and the note above that function is
        the rule;
      * a class-level `__slots__ = (...)` — the one class-level assignment
        that names fields instead of storing one, contributing the names it
        lists rather than the name `__slots__`. Names it lists are never
        demoted: that is a declaration of instance storage in the language;
      * any `<receiver>.<name>` a method of this struct touches — the
        Python-style spelling, in which the fields are whatever `__init__`
        assigns.

    Reading only the class body measured `imports.Resolver` — which assigns
    `path`, `gcc`, `flags` and `_modules` in `__init__` and declares nothing —
    as a struct of NO fields, i.e. as one word. The consequence was not a
    refusal but a wrong answer: each field became a separate function-local
    slot spelled `self.<field>`, the receiver word was never written by
    anything, and every accessor returned an uninitialised register. A formal
    backend that mismeasures a struct and then computes on the wrong storage is
    worse than one that refuses, so the set is derived.

    A name that appears in two of those places is ONE field, not two: a class
    that declares `x: int` and also assigns `self.x = 0` has one field.

    What it still cannot do: with no evidence attached it counts a class-level
    constant as a field, because it cannot see the unit that would settle it.
    That remains the conservative direction — see the note above
    `struct_class_constants` — and it is why a reported width is an UPPER
    BOUND whenever the evidence is missing, which is why every refusal that
    quotes one also quotes the names it counted."""
    split = _split_declaration(struct_def)
    if split is None:
        return _pre_rule_field_names(struct_def)
    return list(split[0])


def _pre_rule_field_names(struct_def) -> list:
    """The field set as it was before constants were separated out: all of them.

    What `struct_field_names` returns for a struct with no evidence attached,
    and what it returned for every struct before this rule existed. Kept as its
    own function rather than inlined so the two derivations cannot drift apart
    in their handling of `__slots__` and of `self.<name>` — the parts that are
    not about constants at all."""
    names, seen = [], set()

    def add(name):
        if isinstance(name, str) and name not in seen:
            seen.add(name)
            names.append(name)

    for field in struct_fields(struct_def):
        declared = _slots_names(field.value) \
            if isinstance(field, F.AssignStmt) \
            and struct_field_name(field) == SLOTS_FIELD else []
        if declared:
            for name in declared:
                add(name)
        else:
            add(struct_field_name(field))
    receivers = struct_receivers(struct_def)
    for method in struct_methods(struct_def):
        touched = set()
        _self_field_names(getattr(method, "body", None), touched, receivers)
        for name in sorted(touched):
            add(name)
    return names


def struct_field_count(struct_def) -> int:
    """How many fields the struct has — the derived count, never the raw one.

    `len(struct_fields(st))` answers a different and much weaker question (how
    many the class body declares) and is what this used to return; see
    `struct_field_names` for what went wrong when that was the answer."""
    return len(struct_field_names(struct_def))


def struct_sole_field_name(struct_def):
    """The name of the struct's one field, or None if it does not have exactly one.

    Read out of the DERIVED field set rather than out of `StructDef.fields[0]`,
    because a one-field struct need not have declared its field: a class whose
    `__init__` assigns `self.n` has one field and no field node at all, so
    indexing the declared list for it either found a different struct's idea of
    the fields or found nothing."""
    names = struct_field_names(struct_def)
    return names[0] if len(names) == 1 else None


# How many field names a width diagnostic will spell out before it says "and
# more" instead. A refusal that lists 263 names has replaced a usable message
# with a wall of text, and the names are there to let the reader CHECK the
# count, which a prefix does just as well as the whole census.
MAX_LISTED_FIELDS = 6


def struct_field_summary(struct_def) -> str:
    """`N fields: a, b, c` — the width, and the names behind it.

    Every refusal that quotes a width quotes the names too, because the derived
    count is an UPPER BOUND — a class-level name the unit's evidence could not
    clear is still counted, and one with no evidence attached counts every
    declared name — and a bare number would be asking the reader to trust a
    census they cannot check. The list is bounded by `MAX_LISTED_FIELDS`:
    past that the count itself is the news and the first few names are enough
    to confirm the tool looked at the class you think it did.
    """
    names = struct_field_names(struct_def)
    if not names:
        return "no fields at all"
    if len(names) <= MAX_LISTED_FIELDS:
        return f"{len(names)} field(s): {', '.join(names)}"
    return (f"{len(names)} fields (too many to list; the first "
            f"{MAX_LISTED_FIELDS} are {', '.join(names[:MAX_LISTED_FIELDS])})")


def struct_width_cost(struct_def) -> str:
    """What closing this particular gap would take, in one clause.

    With the by-reference receiver on (the default; see
    `wide_receiver_by_reference`) a width above one is no longer a wall at all
    and the text says so, because a diagnostic that describes a problem the
    tool has already solved sends the reader looking for a bug that is not
    there. What is still not closed is named instead: the *proof* side of a
    wide receiver is reached only for the cases
    `bugs/FORMAL_wide_receiver_by_reference.md` records."""
    n = struct_field_count(struct_def)
    if wide_receiver_by_reference():
        return (f"{n} fields is a frame of {n} 8-byte slots with a pointer "
                f"receiver, which is the same code as any other width; what is "
                f"still per-width is the proof (a method's callee contract is "
                f"stated modulo its receiver frame — Refine.FrameOk_except)")
    if n == 2:
        return ("two fields is a one-word model plus a second word: an ABI "
                "change, and the cheapest of the widths to close")
    if n <= MAX_LISTED_FIELDS:
        return (f"{n} fields is that same ABI change with a layout to invent: "
                f"a frame slot per field, and a receiver that is a pointer to "
                f"it rather than the value")
    return (f"{n} fields is not an ABI special case at all: it needs a calling "
            f"convention that passes aggregates, a register allocator that can "
            f"spill one, and a proof model whose values are no longer one word")


# ── A multi-field receiver, BY REFERENCE ───────────────────────────────
#
# A value on this path is one 64-bit word, and a struct of two fields has
# nothing to *be* as a value.  It can nevertheless be given a representation
# WITHOUT changing the value model at all, by lowering the receiver **by
# reference**: the receiver word is the ADDRESS of an out-of-line frame of
# 8-byte slots, `self.<field>` is a load from `mem[base + 8*k]`, and a field
# write is a store to the same place.  A pointer is one word, so nothing that
# was one word before becomes two — `MojoFunc`'s single parameter is already
# `self` and is already the address, so `_rewrite_method_calls` needs no change
# at all, and `Refine.Post` / `contract_sound` / `runProg` (already
# `UInt64 → UInt64`) are untouched.
#
# The full design, its cost, and the proof-side algebra (`ProofLib.Frame`,
# `ProofLib.MF`, `Refine.FrameOk_except`) are in
# `bugs/FORMAL_wide_receiver_by_reference.md`.  What is here is the part the
# two backends have to agree on, which is why it is in the shared model rather
# than in either of them: a width that the build pass and the codegen pass
# measured differently is a struct whose receiver is the wrong number of bytes
# in one of them, and neither would notice.
#
# The switch.  Off means the pre-by-reference behaviour exactly: a wide
# receiver is refused by name, and every struct of at most one field is
# unaffected either way (a one-word struct's receiver IS its field, which is a
# different representation and the cheaper one).  It exists so the switch can
# be turned off to attribute a regression, and so a reader can see that nothing
# below it changes a one-field program.
WIDE_RECEIVER_ENV = "MOJO_FORMAL_WIDE_RECEIVER"


def wide_receiver_by_reference() -> bool:
    """Whether a multi-field receiver is lowered as a pointer to a frame.

    ON by default.  The two settings differ ONLY for a struct with more than
    one derived field, and for such a struct the "off" setting is a refusal —
    so turning it on can only turn a refusal into a build, never change the
    meaning of a program that already built.  `MOJO_FORMAL_WIDE_RECEIVER=0`
    restores the refusal, which is what one does to attribute a regression to
    this change rather than to whatever else moved."""
    return os.environ.get(WIDE_RECEIVER_ENV, "1") not in ("0", "no", "false")


def struct_is_framed(struct_def) -> bool:
    """True when this struct's receiver is a POINTER to a frame of fields.

    The complement of `struct_fits_one_word` for every struct of more than one
    field, and `False` for the one-field ones whatever the switch says: a
    one-field struct's receiver is its field, so it needs no frame and there is
    no reason to spend a word of indirection on it."""
    return struct_field_count(struct_def) > 1 and wide_receiver_by_reference()


def struct_frame_slots(struct_def) -> list:
    """The slot contents of a framed receiver, in slot order.

    Slot `k` holds field `k`, and that is the WHOLE of the per-struct layout
    this path needs: no padding, no alignment games, no field reordering.  The
    order is `struct_field_names`'s, which is a stable, documented order, so a
    slot index is a function of the class body and nothing else.

    `ProofLib.Frame.SLOT` / `frameOffset` is the same layout stated on the Lean
    side; `struct_frame_slot` is the `slotOf` table `Frame.SlotOf` requires."""
    return struct_field_names(struct_def)


def struct_frame_slot(struct_def, name):
    """The slot index field `name` occupies, or None if it is not a field.

    Injective because the slot list has no duplicates (`struct_field_names`
    de-duplicates), which is exactly `Frame.SlotOf`'s requirement: a write to
    one field must be invisible to a read of another."""
    names = struct_frame_slots(struct_def)
    return names.index(name) if name in names else None


# A local name does not always have ONE struct. `x = A()` on one path and
# `x = B()` on another is ordinary Python, and on this path both are frame
# addresses — of DIFFERENT frames, with DIFFERENT layouts. Which one a use of
# `x.f` means depends on the branch, and there is no path sensitivity here to
# answer it.
#
# The consequence is not a refusal; it is a wrong answer waiting to happen, and
# it is the reason this function exists. Two structs of two fields each:
#
#     struct A:  var v; var pad      ->  v is slot 0
#     struct B:  var pad; var v      ->  v is slot 1
#
#     def pick(c):
#         var x = A()
#         if c > 0: x = B()
#         return x.v
#
# An analysis that settles on ONE struct computes a slot index from it and
# emits `LDR [x, #8k]` — so on the `A` path it reads A.pad and on the `B` path
# it reads B.pad, and both are a number the source never wrote. The program
# builds, it runs, and it is wrong, which is the outcome this whole design
# exists to make impossible.
#
# So the rule is: AGREE or REFUSE. If every candidate struct puts `name` at the
# same slot index, the access is well defined whichever frame the name holds
# and is emitted once. If they disagree — or one candidate has no such field —
# there is no `k`, and the caller refuses naming the candidates and the slots
# they wanted. Nothing here infers a type; the caller supplies the candidates it
# recognised from the BINDINGS, and an empty candidate set means the name holds
# a plain word rather than a frame address at all.
def struct_frame_slot_candidates(structs, name):
    """`(slot, disagreeing)` — the one slot `name` can be at, if they agree.

    `structs` is the candidate list for the holder, in a stable order.
    `disagreeing` is `(True, [(struct_name, slot_or_None), …])` when there is no
    single answer, and `None` otherwise. An empty candidate list yields
    `(None, (False, []))`: the name is not a frame address, so there is no slot
    to compute and the caller's ordinary value lowering applies.

    "No single answer" has TWO shapes and both are disagreement, which is the
    part worth stating because only one of them looks like disagreement:

      * the candidates put `name` at DIFFERENT slots — `A` has it first, `B`
        has it second; or
      * SOME candidate has it and some do not — `A` has `pad` and `B` does
        not, so on the `B` path the access is a read of a word this layout
        never defined.

    The second is the one a "do they agree on the index?" test written as
    `len(slots) > 1` misses, and it is not a rare shape: any name rebound to a
    struct with a different field set produces one, and reading the agreed
    index anyway is the silently-wrong answer. `rows` is returned either way
    because the refusal has to name WHICH candidate lacks it."""
    rows, slots, have = [], set(), 0
    for st in structs:
        slot = struct_frame_slot(st, name)
        rows.append((st.name, slot))
        if slot is not None:
            slots.add(slot)
            have += 1
    if len(slots) > 1 or have != len(rows):
        return (None, (True, rows))
    return ((slots.pop() if slots else None), (False, rows))


def struct_frame_bytes(struct_def) -> int:
    """How many bytes of stack one instance of this struct's frame occupies.

    8 per field, rounded UP to a multiple of 16 because that is the stack
    alignment AAPCS requires and the receiver frame is carved out of the
    function's own prologue rather than out of the expression-evaluation push
    area — so the rounding has to keep the frame pointer 16-byte aligned."""
    n = 8 * struct_field_count(struct_def)
    return n + (-n % 16)


def struct_field_default(struct_def, name) -> tuple:
    """`(kind, payload)` — the word slot `name` holds in a FRESH instance.

    The per-field reading of the same rule `struct_default_word` states for a
    one-field struct, and deliberately the same rule: only a LITERAL class-level
    initializer is materialized, because a literal has no free names and so has
    the same value at every call site in every function.  Anything else — a
    name, a call, a container — is `(DEFAULT_OPAQUE, name)`, and the caller
    refuses the constructor naming the field rather than substituting 0, which
    is the one answer a formal backend may not invent.

    A field with no class-level initializer at all (`x: Int`, or a field only
    ever assigned in `__init__`) is `(DEFAULT_NONE, None)`: a fresh word of
    zeros, which is what the constructor has always emitted for one."""
    for field in struct_fields(struct_def):
        if struct_field_name(field) == name:
            return class_constant_word(name, getattr(field, "value", None))
    return (DEFAULT_NONE, None)


def struct_frame_defaults(struct_def) -> list:
    """`[(kind, payload)]` per slot, in slot order — what `S()` must store."""
    return [struct_field_default(struct_def, name)
            for name in struct_frame_slots(struct_def)]


def struct_frame_representable(struct_def):
    """`(ok, reason)` — can `S()` bring every one of this struct's fields up?

    `ok` is False exactly when some field's declared default is a real value
    this path cannot evaluate at a call site.  The reason names the field,
    because a refusal that does not is a refusal the reader has to re-derive."""
    for name, (kind, payload) in zip(struct_frame_slots(struct_def),
                                     struct_frame_defaults(struct_def)):
        if kind == DEFAULT_OPAQUE:
            return (False, name)
    return (True, None)


def framed_struct_names(structs) -> dict:
    """`{name: struct}` for every struct whose receiver is a frame pointer.

    The set the build pass hands the two backends, read out of the SHARED
    model rather than recomputed per backend, so that the pass that lifts a
    method and the pass that emits its field accesses cannot disagree about how
    wide the receiver is."""
    return {st.name: st for st in structs if struct_is_framed(st)}


# The largest slot offset `LDR Xt, [Xn, #imm]` / `MOV Xt, [Xn+imm]` can name
# without computing the address: the arm64 unsigned-offset form's imm12 is 12
# bits of EIGHT-BYTE units, so slot 4095 is the last one addressable directly.
# A struct wider than this is refused by name rather than given a second
# addressing mode, because a second addressing mode is a second thing to get
# right and this path's whole value is that there is one.
MAX_FRAME_SLOT = 4095


def struct_frame_fits_encoder(struct_def) -> bool:
    """Whether every one of this struct's slots is directly addressable."""
    return struct_field_count(struct_def) <= MAX_FRAME_SLOT + 1


def iter_nodes(node):
    """Every dataclass node in a statement tree, parents before children.

    Shared because the frame layout (`struct_constructor_sites`), the
    frame-holder analysis (`formal/build.py`) and the constant-read census all
    have to walk the SAME tree the same way; three private copies of this loop
    are three chances for one of them to see a node the others do not, and a
    node one of them missed is a frame nobody reserved."""
    if isinstance(node, (list, tuple)):
        for x in node:
            yield from iter_nodes(x)
        return
    if not hasattr(node, "__dataclass_fields__"):
        return
    yield node
    for name in node.__dataclass_fields__:
        yield from iter_nodes(getattr(node, name))


def struct_constructor_sites(fn, structs_by_name) -> dict:
    """`{id(call): (struct, offset)}` — this function's receiver frames.

    A layout decision, so it lives in the shared model and both backends read
    the same answer: a frame is reserved in the function's PROLOGUE, so it has
    to exist before the body runs and cannot be handed out by a bump pointer
    that walks the body the way the list/dict blob cursor does.

    One frame per call SITE, laid out in walk order. Per site rather than per
    call is what makes a constructor inside a loop safe: the loop reuses its
    site's frame, exactly as a C local is reused, so a loop cannot grow the
    stack without bound. `offset` is the frame's distance below the bottom of
    the function's ordinary frame — below `SP` on both machines, which is the
    placement `ProofLib.Frame.frameWrite_read_above_sp` needs and the reason a
    method's write to its receiver cannot reach the caller's window.
    """
    framed = framed_struct_names(list(structs_by_name.values()))
    if not framed:
        return {}
    out, offset = {}, 0
    for node in iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.CallExpr) or not isinstance(node.func,
                                                             F.IdentExpr):
            continue
        st = framed.get(node.func.name)
        if st is None:
            continue
        out[id(node)] = (st, offset)
        offset += struct_frame_bytes(st)
    return out


# What a FRESH one-word value has to hold, and whether this path can produce it.
#
# `S()` is not a call; it brings every field up at its default. For a struct of
# zero or one field that default is the whole value, so a constructor that
# always emitted 0 was quietly throwing it away — `struct Counter: count = 7`
# with a `get()` that only READS the field returned 0. It built, it ran, and it
# was wrong, which is the one outcome a formal backend may not produce.
#
# Only LITERAL defaults are materialized, deliberately. A default written as a
# name (`count = TABLE_SIZE`) or an expression cannot be evaluated at the
# constructor's call site without knowing what is in scope there, and a
# constructor that guessed would be the same bug wearing a hat. A literal has no
# free names, so there is nothing to resolve and the answer is the same at every
# call site in every function.
DEFAULT_NONE = "none"          # no default to speak of: zero is correct
DEFAULT_INT = "int"
DEFAULT_STRING = "string"      # a formal string is a bare `char *`: one word
DEFAULT_OPAQUE = "opaque"      # a real default this path cannot bring up


def struct_default_word(struct_def) -> tuple:
    """`(kind, payload)` — what `S()` must leave in the word for this struct.

    ("none", None) when there is no class-level initializer to honour, which
    includes every field with no value (`x: Int`) and every zero-field marker:
    a fresh word of zeros is right for both, and is what the constructor emitted
    before this existed.

    ("int", n) / ("string", s) when the sole field's default is that literal,
    which both backends can materialize exactly (a string is its own address).

    ("opaque", field_name) when there IS a default and it is not a literal —
    a container, a name, a computation. The caller must refuse rather than
    substitute 0, because substituting 0 is precisely the wrong answer this
    function exists to prevent.

    Only meaningful for a struct of at most one field; a wider one brings each
    of its fields up separately, through `struct_frame_defaults`."""
    if struct_field_count(struct_def) != 1:
        return (DEFAULT_NONE, None)
    field_name = struct_sole_field_name(struct_def)
    default = None
    for field in struct_fields(struct_def):
        if struct_field_name(field) == field_name:
            default = getattr(field, "value", None)
            break
    kind, payload = literal_default_word(default)
    return (kind, field_name if kind == DEFAULT_OPAQUE else payload)


def literal_default_word(value) -> tuple:
    """`(kind, payload)` for a class-body initializer — the ONE reading of it.

    A literal has no free names, so its value is the same at every read site in
    every function and either backend can materialize it exactly. Anything else
    — a name, a call, a container display — needs a scope this path does not
    have at a use site, and is (DEFAULT_OPAQUE, None) so each caller can name
    what it could not bring up.

    Shared by `struct_default_word` (a field's default, materialized by the
    constructor) and `class_constant_word` (a class-level constant, materialized
    at each read of it) because they are the same question asked of the same
    node, and two copies of this decision would eventually disagree about which
    defaults are representable."""
    if value is None:
        return (DEFAULT_NONE, None)
    if isinstance(value, F.IntLiteral):
        return (DEFAULT_INT, int(value.value))
    if isinstance(value, F.BoolLiteral):
        return (DEFAULT_INT, 1 if value.value else 0)
    if isinstance(value, F.StringLiteral) \
            and isinstance(value.value, str) and not value.is_bytes:
        return (DEFAULT_STRING, value.value)
    return (DEFAULT_OPAQUE, None)


def class_constant_word(name: str, default) -> tuple:
    """`(kind, payload)` — what a read of the class constant `name` yields.

    The same contract as `struct_default_word`, for the other kind of class-body
    initializer: a class-level constant is not brought up by `S()` (there is no
    constructor to bring it up in — a constant has one value for every instance,
    so it is not part of the value), it is materialized where it is READ.

    Which is why a constant that is not a literal has to be refused rather than
    read as the zero an unwritten slot would give: there is no module-global
    storage on this path (see the backends' handling of `global NAME`), so a
    bare `S.NAME` read has nothing to bind to, and 0 would be a plausible-
    looking wrong number rather than a crash."""
    kind, payload = literal_default_word(default)
    return (kind, name if kind == DEFAULT_OPAQUE else payload)


def struct_fits_one_word(struct_def) -> bool:
    """True when the struct's whole state is a single word.

    Zero fields (a marker) and one scalar field are both exactly one word: for
    the single-field case the receiver IS the field, so `self.n` is `self` and
    no indirection is needed anywhere. The count is the DERIVED one, so a class
    that assigns its field in `__init__` gets the same treatment as one that
    declares it — which is what makes `self.n` and `c.n` the same storage
    instead of two unrelated words that happen to share a spelling.

    A `False` here no longer means "cannot be lowered" once
    `wide_receiver_by_reference()` is on: it means "not a one-word value", and
    `struct_is_framed` is the question that decides which of the two
    representations the receiver gets."""
    return struct_field_count(struct_def) <= 1


def method_function_name(struct_name: str, method_name: str) -> str:
    """The internal symbol a struct's method compiles to.

    Flat and module-agnostic, because it has to be callable from a direct BL
    within one image; the module-qualified ABI spelling is applied at the
    export boundary (see abi_method_symbol) where it is actually needed."""
    return f"{struct_name}_{method_name}"


def abi_method_symbol(module_prefix: str, struct_name: str,
                      method_name: str) -> str:
    """The boundary symbol for a struct method, per doc/ABI.md.

    Module-qualified, so two modules' same-named structs never collide in one
    library — the same reason a free function's export is qualified."""
    return f"{module_prefix}_{struct_name}_{method_name}"


def struct_methods(struct_def) -> list:
    return list(getattr(struct_def, "methods", None) or [])


def find_method_owner(structs: dict, method_name: str):
    """The struct that declares `method_name`, or None.

    Dispatch here is by name alone because that is all a `recv.m()` call site
    carries: the receiver's type is not inferred on this path. A method name
    declared by two structs in one module is therefore ambiguous, and the
    caller is expected to refuse it rather than pick one."""
    owners = [st for st in structs.values()
              if any(m.name == method_name for m in struct_methods(st))]
    if len(owners) == 1:
        return owners[0]
    return None


def method_owner_names(structs: list) -> dict:
    """{`<Struct>_<method>` function name: struct} for every declared method.

    The reverse of find_method_owner, for the compiler side: after a method is
    lifted to a function, this is what identifies which struct's layout the
    body is written against."""
    out = {}
    for st in structs:
        for m in struct_methods(st):
            out[method_function_name(st.name, m.name)] = st
    return out
