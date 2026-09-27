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


def mlir_template_refusal(e):
    """The refusal for an MLIR template in any spelling, or None if `e` is not one.

    The text is `multi_index_refusal`'s, unchanged and still ARCH-FREE: it was
    already correct for the one spelling that reached it, and the defect was
    that the other two spellings did not. Naming the construct — not the
    symptom — is what makes it usable on a file nobody has read."""
    if not is_mlir_template(e):
        return None
    return multi_index_refusal(MULTI_INDEX_MLIR_TEMPLATE,
                               mlir_template_spelling(e))


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
    `limit_comptime_over_a_runtime_parameter` is pinned against."""
    for st in stmts:
        value = getattr(st, "value", None)
        if value is None or not isinstance(st, F.ComptimeVarStmt):
            continue
        for node in iter_nodes(value):
            why = mlir_template_refusal(node)
            if why is not None:
                raise CodegenError(
                    f"the module-level comptime binding "
                    f"{getattr(st, 'target', '?')!r} is initialized from an MLIR "
                    f"attribute template: {why} Module-level `comptime` "
                    f"bindings are not part of the function-body expression "
                    f"walk on this path, so nothing used to refuse this and the "
                    f"binding read as an undefined name at every use site.")
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
    if is_mlir_template(e):
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
    the read-only check this replaces left `a[i, j] = v` unrefused.

    Callable UNCONDITIONALLY — the multi-element gate moved inside — because the
    MLIR answer does not depend on the arity (`is_mlir_template` keys on the
    base), and a caller that still guarded the call with `is_multi_index` would
    keep the single-element spelling `__mlir_type[x]` fabricated. A non-MLIR
    single index is not this function's business and returns None, exactly as
    before."""
    why = mlir_template_refusal(e)
    if why is not None:
        return why
    if not is_multi_index(getattr(e, "index", None)):
        return None
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

# ── THE STRING REPRESENTATION, and why it is a bare `char *` ──────────────
#
# Wave 3 asked the same question of a multi-field struct and answered it
# BY REFERENCE: a pointer is one word, so a struct that does not fit in a word
# is reached through a pointer rather than widened. The same question has to be
# asked here, and the answer is the same shape — but it is worth being precise
# about WHY, because the two reasons are different and only one of them
# generalises.
#
# For a struct, by-reference was the only option: the fields have to live
# somewhere, and a word is all a value is. For a string, by-reference is
# available AND SUFFICIENT, because the representation is already a reference
# and the thing it refers to is not a frame:
#
#   1. A string on this path is a bare `char *` into the image's own text. The
#      bytes are interned by content (`_intern_string` in either backend) and
#      emitted into `__TEXT,__text`, which is mapped `initprot 0x5` — read and
#      execute, no write. Measured on a built image, not assumed:
#
#         SEG __TEXT  maxprot=0x5 initprot=0x5
#            __TEXT,__text addr=0x100000320 size=139
#         ... the last bytes of __text: b'hello\x00len=%d\\n\x00'
#
#      So a string is NUL-TERMINATED and the terminator is there. That one fact
#      is what makes the next point possible, and it is worth separating from
#      the rest: it is a property of the C representation, not of this backend.
#
#   2. Therefore the length is a COMPUTATION, not a FIELD. `strlen(s)` is the
#      length of a NUL-terminated `char *` by definition, so the missing length
#      costs one libc call and no storage, no second word, and no lifetime. The
#      same argument makes `==` a computation: `strcmp(a, b) == 0` is the
#      content equality of two NUL-terminated `char *`s. Both symbols are
#      ALREADY emitted by both backends — `endswith`, `count` and `f.write(s)`
#      all call `strlen`, and nothing here is new machinery.
#
#   3. A string is also the ONE pointer on this path with no lifetime problem.
#      Every string value is either a literal's bytes or an interior pointer
#      into them (`lstrip` is the only method that yields a string, and it
#      yields `s + strspn(...)`), so every string value has STATIC storage
#      duration: it is as safe to return from the function that made it, to
#      store in a container, or to hand to a callee as a frame address is not.
#      Measured, both backends, on a program that does exactly that:
#
#          def make():
#              s = "  hi".lstrip()
#              return s
#          def main(n):
#              printf("[%s]\n", make())      # -> [hi]
#
#   Point 3 is the load-bearing one for the representation question, and it
#   cuts the OTHER way from what a descriptor would want. A `{ptr, len}`
#   descriptor would put the length in a field, which means the descriptor has
#   to live somewhere: a frame (and then it inherits the frame's lifetime, so
#   every `lstrip` result would have to be refused for the same reason a struct
#   frame address is, LOSING the one string method that works today) or a heap
#   (and there is none). It would also not survive `lstrip`, which produces an
#   interior pointer with no descriptor of its own. So the descriptor is not a
#   cheaper answer — on this path it is strictly more expensive, and it buys
#   back nothing that `strlen` was not already giving.
#
# THE COST, stated rather than hidden:
#
#   * `len(s)` and `s == t` are O(n) where interning made `==` O(1) between two
#     literals. On a backend whose job is to be trustworthy rather than fast,
#     that is the right trade, and it is still a trade.
#   * A string value here CANNOT CONTAIN A NUL, because the NUL ends it. A
#     real Mojo `String` can, and `len` of a string with an embedded NUL would
#     be wrong. Nothing lowered today can produce one — every string is a
#     literal or an interior pointer into a literal — so this is a latent gap,
#     not a live wrong answer, and it is recorded here so that whoever adds the
#     first method that can build a string at run time inherits the obligation.
#   * Equality by CONTENT costs a call, and `is` / `is not` (identity) must
#     therefore NOT be lowered as `strcmp`: they are the one string comparison
#     that genuinely wants the pointer. See STRING_IDENTITY_OPS.
#
# And the cost that is NOT paid, which is the whole point: no value on this
# path gets wider, so nothing above this line has to be re-derived by anything
# that reasons about word-sized values — the struct refusal, the frame slot
# tables, the one-word field map, the call ABI, and all ~40 passing proofs.
#
# What this decision does NOT settle, and is the actual blocker in the stdlib:
# the name `String` denotes TWO different things, and only one of them is the
# representation described here. `std/collections/string/string.mojo` declares
#
#     struct String:
#         var _ptr_or_data: Pointer[UInt8]
#         var _len_or_data: Int
#         var _capacity_or_data: Int
#
# — three fields, so wave 3's by-reference receiver makes a `String` local the
# ADDRESS of a three-slot frame (verified: `struct_is_framed(String)` is True,
# `struct_frame_slots` is 3), and the frame-lifetime rule then refuses to let
# one be returned or passed on. That is where all 16 of the "a String receiver
# is returned/passed" refusals in the stdlib sweep come from, and it is NOT a
# consequence of anything above: the same program with the string kept as a
# `char *` builds and runs on both backends. Note that the length is RIGHT
# THERE, in slot 1 — so "a string needs a length" is not the problem these 16
# files have; they have a length and cannot keep it. See
# bugs/FORMAL_string_value_model.md, which records the decision, the cost, and
# the two representations' collision.

# The two libc symbols this representation makes available, named once so a
# backend cannot spell one of them two ways and so the docstring above has
# something concrete to point at.
#
# The comparison is `strncmp` and NOT `strcmp`, and the reason is measured
# rather than aesthetic. `strcmp(a, b) == 0` is the obvious spelling and it
# works on arm64 — but on x86-64 an image whose only `strcmp` call sites were
# the ones this lowering emitted returned FALSE for `"abc" == "abc"`, with the
# emitted code, the interned addresses, the `__TEXT,__stubs` entry and the
# `__DATA_CONST,__got` slot all verified correct by hand. A new libc symbol on
# the x86-64 extern path is therefore not something to introduce casually, and
# the fix that is verifiable on both architectures uses the two symbols the
# backends ALREADY call for `startswith` and `f.write(s)`:
#
#     strncmp(a, b, strlen(b) + 1) == 0
#
# which is exactly `a == b` for NUL-terminated strings — comparing one byte
# past `b`'s last character means the compare cannot succeed unless it also
# compared `b`'s NUL, so it cannot succeed unless `a` ends there too. One extra
# `strlen` and one extra `add`, no new symbol, and both halves are the same
# libc calls the same two backends already make. See
# bugs/FORMAL_string_value_model.md for the x86-64 observation and what it does
# and does not establish.
STRING_LENGTH_SYMBOL = "strlen"
STRING_COMPARE_SYMBOL = "strncmp"

# How `len(x)` lowers, by the kind of `x`. The two that CAN be lowered are the
# two representations that carry the count somewhere findable: a blob in a
# field at offset 0, a string as a computation over its bytes. Everything else
# is None, and None is a REFUSAL — see `len_refusal`.
LEN_FROM_BLOB_FIELD = "blob_count_field"
LEN_FROM_STRLEN = "strlen"

# `is` / `is not` on two strings. The one string comparison that wants the
# POINTER and not the bytes, and the reason the content comparison above cannot
# be applied to it: `a is b` asks whether two names hold the same object, and
# with interning by content two equal literals ARE the same object, so the
# pointer compare is the answer rather than an approximation of it. Lowering
# `is` as `strcmp` would make `"ab" is "ab"` true for the right reason and
# `x is y` true whenever the contents match, which is a different question with
# the same spelling. Left unlowered, and refused by `string_comparison_refusal`
# with that said.
STRING_IDENTITY_OPS = ("is", "is not")

# The two answers a string comparison can have. Content is `strcmp(a, b) == 0`;
# identity is the pointer compare, which is what `is` asks for.
STRING_COMPARE_CONTENT = "content"
STRING_COMPARE_IDENTITY = "identity"


def len_operand_lowering(kind, expr=None) -> str | None:
    """How `len(x)` lowers for an operand of kind `kind`, or None to refuse.

    Shared by both backends, and the sharing is the point: the two
    architectures had one shared table deciding WHICH string methods exist and
    two private copies of the `len` decision, and the private copies disagreed
    with each other about what a string is — arm64 refused a string literal and
    read a count field for a local, x86-64 did the same, and neither asked what
    the local actually held. One table, one answer.

    `kind` is what the classifier says, and `None` means the source does not
    say. None is the case this function exists for: the old lowering read eight
    bytes at offset 0 of an unclassified word and called the result a length,
    which for a `char *` is the first eight CHARACTERS of the string. Measured
    on both architectures, `len(m)` where `m = "hello"` returned 1819043176 —
    which is 0x6C6C6568, the bytes `hell` read little-endian, and for
    `"  hi".lstrip()` it returned 536897896, which is 0x20006869, `hi` plus the
    two spaces that were trimmed. Both BUILT, both RAN, both were wrong, and
    the wrong number was indistinguishable from a right one. So the
    unclassified case is refused rather than guessed, and the refusal names it.

    `expr` is the operand node, for the shapes whose count is a fact about the
    LOWERING rather than about the kind. `range(...)` is the one that exists
    today: both backends materialise it as a `[count][elements]` blob
    (`_emit_range_list`), so its length is that blob's count field — but
    `_kind_of_call` still classifies a `range(...)` call as an integer, so the
    kind alone refuses a `len(range(10))` that has always worked and is
    covered by `len_range` in test_formal_run.py. Recognising it here, by the
    shape that decides the answer, is the honest form: the answer does not
    depend on the kind being right, it depends on what the range lowers to.

    That inconsistency is left in place rather than papered over on both sides:
    a `range(...)` is a list blob and calling it an `int` is wrong, but
    `print(range(3))` currently formats it as a number and is therefore already
    printing a blob address as if it were a count. Correcting the kind fixes
    `len` and has to be considered together with that, which is a change to the
    kind table rather than to the string representation.
    """
    if kind == STR_KIND:
        return LEN_FROM_STRLEN
    if is_list_kind(kind) or lowers_to_counted_blob(expr):
        return LEN_FROM_BLOB_FIELD
    return None


# The call-shaped things this path materialises as a `[count][elements]` blob
# and that the kind table does not (yet) classify as one. `range` is the only
# member; the container LITERALS are already `list_kind(...)` by
# `ValueKinds.kind_of`, and a comprehension too, so they need no row here.
# Named rather than inlined so that the reason above has one place to live.
_COUNTED_BLOB_CALLEES = ("range",)


def lowers_to_counted_blob(expr) -> bool:
    """True when `expr` is emitted as a blob whose first 8 bytes are its count.

    A LOWERING fact and not a kind fact, which is why it is a predicate over
    the node and not a row in the kind table: it is consulted only by
    `len_operand_lowering`, and only because the kind table does not yet say
    this. See that function for the `range` case and for why the kind is left
    alone rather than corrected here.
    """
    if isinstance(expr, F.CallExpr):
        return _flat_callee(expr) in _COUNTED_BLOB_CALLEES
    return False


def len_refusal(kind, spelled: str) -> str | None:
    """Why `len({spelled})` cannot be lowered, or None when it can.

    One message for both backends, and it says which of the two things is
    missing rather than restating the rule:

      * a string's length is a `strlen` over its bytes, so a refusal here means
        the operand is NOT known to be a string, not that strings have no
        length;
      * a blob's length is its count field, so an int has no such field and
        reading offset 0 of it is a word, not a count;
      * an unclassified operand is the case that used to produce a number. It
        gets its own sentence, because it is the one a reader has to act on:
        annotate the name, or bind it to something this path can see the type
        of.
    """
    how = len_operand_lowering(kind)
    if how is not None:
        return None
    if kind is None:
        return (
            f"len({spelled}) — the source does not say what this operand holds, "
            f"and on this path the two things len() can answer are told apart "
            f"by what the operand IS: a string is a bare char * whose length is "
            f"a strlen over its bytes to the NUL, and a list or tuple is a "
            f"frame-allocated blob whose count is its first 8 bytes. Reading 8 "
            f"bytes at offset 0 of an unclassified word is a plausible-looking "
            f"wrong number — for a char * it is the first eight CHARACTERS of "
            f"the string — so it is refused. Annotate it (`x: String`) or bind "
            f"it to a list, tuple, range or string literal this path can see "
            f"the shape of")
    if kind == INT_KIND:
        return (
            f"len({spelled}) is len() of a value classified as {kind!r}, and "
            f"an integer has no length: there is no count to read at offset 0, "
            f"and the word there is the integer itself. A string's length is a "
            f"strlen over its bytes and a list's is its count field, and an int "
            f"is neither")
    return (
        f"len({spelled}) is len() of a value classified as {kind!r}, and this "
        f"path has no length to read for it. A string's length is a strlen "
        f"over its bytes to the NUL and a list's is the count field at offset "
        f"0 of its blob; nothing else here carries one, and returning the word "
        f"itself would be a plausible-looking wrong number")


def string_operand_is_string(kind) -> bool:
    """True when `kind` says the value is a `char *` to NUL-terminated bytes.

    The single question both string lowerings ask, so that `len` and `==`
    cannot end up disagreeing about which values are strings — the
    `string_method_yields_string` lesson, one level down.
    """
    return kind == STR_KIND


def string_comparison_lowering(op: str, left_kind, right_kind):
    """How `a {op} b` lowers when either side is a string: content, identity,
    or None when it is not a string comparison.

    `==` and `!=` are CONTENT, i.e. `strcmp(a, b) == 0` — the same libc call
    `startswith` already makes, for the same reason: it is the algorithm, so
    there is no second implementation of it here to be subtly wrong. The old
    lowering compared the two POINTERS, which is right for two interned
    literals — interning is by content, so equal literals are the same object
    — and wrong for every derived interior pointer, which is exactly what
    `lstrip` returns and what every sub-range method would:

        m = "  abc".lstrip()
        m == "abc"          # False on the pre-change tree, on BOTH backends

    A correct program taking the wrong branch, which is worse than a number
    being wrong: nothing downstream can tell.

    `is` and `is not` stay IDENTITY, i.e. the pointer compare they already
    were, and this is the one place where the pointer is the ANSWER rather than
    an approximation of it: `a is b` asks whether two names hold one object,
    and with interning by content two equal literals already are one object.
    Routing them through `strcmp` would make `x is y` true whenever the
    CONTENTS match, which is a different question spelled the same way. This
    function exists so that the two pairs cannot be routed together by accident
    in one backend and not the other — the cost of getting it wrong is a
    correct-looking comparison that answers the wrong question, on one
    architecture.
    """
    if not (string_operand_is_string(left_kind)
            or string_operand_is_string(right_kind)):
        return None
    if op in ("==", "!="):
        return STRING_COMPARE_CONTENT
    if op in STRING_IDENTITY_OPS:
        return STRING_COMPARE_IDENTITY
    return None


def string_concat_refusal(op: str, left_kind, right_kind) -> str | None:
    """Why `a {op} b` cannot be lowered when BOTH sides are strings, or None.

    The name is historical and the docstring should not pretend otherwise:
    `+` was the only member when this was written, and it is still the one
    carrying the measured transcript. `-` joined it because address minus
    address is the same missing buffer as address plus address, and because
    leaving it out meant `s = s - t` was refused while `s -= t` was not — the
    same operator, two answers, from the same two backends. The augmented
    spellings are in the set because the AUGMENTED emitters are a separate code
    path from the binary ones and have to be caught by name.

    The measured state of `+`, on the pre-change tree and on both backends:

        s = "ab" + "cd"; printf("[%s]\\n", s)

    printed `[]` on arm64 and SEGFAULTED on x86-64. The reason is the
    representation and nothing else: a string is a POINTER, so `+` is integer
    addition of two addresses, and the sum is an address no mapping covers.
    Concatenation is not a longer string, it is a buffer of a size that is a
    function of both operands and that nothing knows at compile time — the same
    missing buffer that keeps `upper` and `replace` in
    LENGTH_DEPENDENT_METHODS. It is listed here rather than there because the
    failure it produces is worse than a refusal in that table: `strip` builds
    and prints a plausible wrong STRING, and this one prints a plausible wrong
    STRING on one architecture and crashes on the other, so the two backends
    do not even agree on whether the program works.
    """
    if op not in STRING_TWO_STRING_ARITHMETIC_OPS:
        return None
    if not (string_operand_is_string(left_kind)
            and string_operand_is_string(right_kind)):
        return None
    return (
        f"{op!r} on two strings is refused on this path. A string here is a "
        f"bare `char *`, so `{op}` is integer arithmetic on two addresses, and "
        f"what it produced was measured: `print(\"ab\" + \"cd\")` printed `[]` "
        f"on arm64 and segfaulted on x86-64. Concatenation needs a buffer whose "
        f"size is a function of both operands, and this path has no heap to "
        f"allocate one in and no writable copy of the receiver's bytes to lay it "
        f"down in — a string literal is interned into __TEXT,__text, which is "
        f"mapped read+execute. This is the same missing buffer that keeps "
        f"`upper`, `replace` and `join` refused; see LENGTH_DEPENDENT_METHODS")


# `+`/`+=` and `-`/`-=`: the operators whose refusal is about TWO strings and
# the buffer their result would need. Every other operator in the arithmetic
# table is refused on a single string operand too, and is not here.
STRING_TWO_STRING_ARITHMETIC_OPS = ("+", "+=", "-", "-=")


# ── Everything else that reaches an INTEGER path holding a `char *` ───────
#
# `string_concat_refusal` above is one operator out of a table, and the reason
# it is one operator is historical rather than principled: it was the operator
# whose failure was MEASURED (`[]` on arm64, SIGSEGV on x86-64) and so the one
# anybody looked at. Every operator below has the same cause — a string is a
# bare `char *`, so any operator that reaches the integer ALU or the flag-
# setting compare is operating on an ADDRESS — and every one of them BUILDS,
# RUNS and returns a number the source never wrote. Measured on the tree this
# was written on, for `s = "abc"; t = "bc"`, on BOTH backends:
#
#     s & t     69911496 (arm64)   45978594 (x86-64)
#     s | t     68191180           2872318
#     s ^ t         4                  28          <- the two architectures
#     s - t        -4                  -4             DISAGREE on a
#     s * 2      8062864            5302246         fabricated number
#     s // 2   -2147433998        -2128240118
#     s >> 1   -2107760164        -2147386903
#     ~s          8881076            3236815
#     -s       -36488120          -79725522
#
# and the RELATIONAL half is worse than a wrong number, because it is a wrong
# BRANCH: `if s < t:` is decided by the interning order of two literals in the
# text section, so the answer is a property of the image's layout rather than
# of the program. On the tree above `s < t` and `s <= t` were TRUE and
# `s > t` and `s >= t` were FALSE, on both backends, purely because `"abc"` is
# emitted before `"bc"`. Reordering the two literals in the source reverses
# every one of them.
#
# So: the same answer as for `+`, for the same reason. None of these is lowered.
#
# The ONE exception, and it is D3's decision rather than this file's, is
# `ptr + int` and `ptr - int` with exactly one string operand. That is real C
# pointer arithmetic, it is the idiom a caller who reached a `char *` through
# this path may have meant, and refusing it would turn a working program into a
# diagnostic over a case the model cannot see. `str_plus_int_still_arithmetic` in
# test_formal_run.py is the guard. Every operator below has NO such reading:
# `%` and `&` on a pointer are not C at all, `|` and `^` are bit operations on
# an address, and `*` would have to scale a pointer to mean anything, which is
# a GNU extension rather than the C this path emits.
STRING_RELATIONAL_OPS = ("<", ">", "<=", ">=")
STRING_BITWISE_OPS = ("&", "|", "^")
STRING_SHIFT_OPS = ("<<", ">>")
STRING_PRODUCT_OPS = ("*", "/", "//", "%", "**")
# `+` and `-` are absent deliberately: `string_concat_refusal` owns them for the
# two-strings case, and the one-string case is the pointer arithmetic above.
STRING_ARITHMETIC_OPS = (STRING_BITWISE_OPS + STRING_SHIFT_OPS
                         + STRING_PRODUCT_OPS + STRING_RELATIONAL_OPS
                         + ("-",))

# Unary operators with no meaning on a `char *`. `~` is a bit operation on an
# address; unary `-` is negation of one. `not` is here too and for a different
# reason — see `string_unary_refusal`.
STRING_ARITHMETIC_UNARY_OPS = ("-", "~")


# The operator as a table key. A trailing `=` marks an AUGMENTED form and the
# tables below are keyed on the bare operator, so `+=` looks up `+`.
#
# The membership test is `AUG_OPS`, NOT "ends with `=`": the comparison
# operators `<=`, `>=` and `!=` end with `=` and are not augmented, and
# stripping their `=` turned `s <= t` into a refusal that named `'<'` — a
# diagnostic about a different operator than the line the reader is looking
# at, which is the one thing a refusal must not be. `==` is excluded for the
# same reason, and it is why `string_concat_refusal`'s own operator set has
# always been safe to spell out.
def _bare_operator(op: str, spelled_op: str | None = None) -> str:
    if op.endswith("=") and op[:-1] in AUG_OPS:
        return op[:-1]
    return op


def string_arithmetic_refusal(op: str, left_kind, right_kind,
                              spelled_op: str | None = None) -> str | None:
    """Why `a {op} b` cannot be lowered when a `char *` is an operand, or None.

    `spelled_op` is what the DIAGNOSTIC should say, which is not always `op`:
    the augmented-assignment emitters strip the `=` (`+=` arrives as `+`), and
    a message that told somebody their `+=` was a `+` would be a small lie
    about the line they are looking at. The table is keyed on the bare operator;
    only the wording uses the spelling.

    The refusal is deliberately not split by whether one or both operands are
    strings, with ONE exception: see `STRING_ARITHMETIC_OPS` for why `+`/`-`
    with a single string operand is left alone. For everything else the answer
    is the same either way — a pointer in an integer operator is meaningless —
    so a message that distinguished them would be longer and say less.
    """
    bare = _bare_operator(op, spelled_op)
    if bare not in STRING_ARITHMETIC_OPS:
        return None
    if bare == "-":
        # `-` is the one operator whose refusal is `+`'s, so it goes through
        # the same function and inherits the same measured numbers. The
        # two-strings case is address minus address — the same missing buffer as
        # address plus address. The one-string case is `ptr - int`, which is
        # real C pointer arithmetic and is deliberately left alone; see the
        # note above on why `+`/`-` are absent from the general table.
        return string_concat_refusal(spelled_op or bare, left_kind, right_kind)
    if not (string_operand_is_string(left_kind)
            or string_operand_is_string(right_kind)):
        return None
    return _string_operand_refusal(bare, spelled_op, left_kind, right_kind)


def _string_operand_refusal(op: str, spelled_op, left_kind,
                            right_kind) -> str:
    """The shared wording for "this operator reached the integer path with a
    `char *` in it". One function so the two backends print the same sentence
    and so adding an operator does not mean writing a second paragraph."""
    shown = spelled_op or op
    which = "the left operand" if string_operand_is_string(left_kind) else (
        "the right operand" if string_operand_is_string(right_kind)
        else "an operand")
    return (
        f"{shown!r} is refused when {which} is a string. A string on this path "
        f"is a bare `char *`, so `{shown}` is an integer operation on an "
        f"ADDRESS, and it builds, runs and returns a number the source never "
        f"wrote: for `s = \"abc\"` and `t = \"bc\"`, `s ^ t` returned 4 on arm64 "
        f"and 28 on x86-64, `s * 2` returned 8062864 and 5302246, and "
        f"`s // 2` returned -2147433998 and -2128240118 — two architectures "
        f"disagreeing about a number neither of them computed. "        + ("Python orders strings lexicographically and this compares their "
           "addresses, so the branch is taken by the order the literals happen "
           "to be interned in the text section: `s < t` measured TRUE and "
           "`s > t` FALSE on both backends for no reason a reader of the "
           "program could see. Lexicographic order needs a three-way compare "
           "and this path has no symbol that provides one. "
           if op in STRING_RELATIONAL_OPS else "")
        + "The string operations that ARE lowered are `len`, `==`/`!=`, `is`/"
        "`is not`, `in`/`not in`, and the methods in POINTER_BOUNDED_METHODS; see "
        "STRING_LENGTH_SYMBOL for why a string's length and content equality "
        "are computations over its bytes rather than fields, and "
        "string_concat_refusal for the `+` half of this table")


def string_binary_refusal(op: str, left_kind, right_kind,
                          spelled_op: str | None = None) -> str | None:
    """The ONE place a binary operator with a string operand is decided not to
    be lowered, so both backends ask the same question in the same order.

    `+`/`+=` first, because that is the one with the measured transcript in it,
    and then everything else that reaches the integer ALU or the flag-setting
    compare. Exists as one entry point rather than two call sites per backend
    precisely because the failure mode being prevented is the two architectures
    disagreeing: the first version of this table was consulted by arm64 and not
    by x86-64 for the augmented forms, so `s += t` printed `[]` on arm64 and
    segfaulted on x86-64 — the same non-answer as `s = s + t`, which both
    backends refused, from the same line of source.
    """
    return (string_concat_refusal(spelled_op or op, left_kind, right_kind)
            or string_arithmetic_refusal(op, left_kind, right_kind,
                                         spelled_op))


def string_unary_refusal(op: str, kind, spelled_operand: str) -> str | None:
    """Why `-s` / `~s` / `not s` cannot be lowered for a string, or None.

    `-` and `~` are the arithmetic table again with one operand: negation of an
    address and a bit complement of one. `not` is here for a different reason
    and is a DIFFERENT KIND of wrong answer, which is why it is worth naming:
    a string is a pointer, and a pointer is never zero, so `not s` is FALSE for
    every string on this path INCLUDING THE EMPTY ONE. Measured, both backends:

        s = "abc"
        e = ""
        printf("%d %d", 1 if not s else 0, 1 if not e else 0)   # -> 0 0

    Python's answer is `0 1`. This one is a fabricated FALSITY — a program that
    tests a string for emptiness is told the empty string is non-empty, and no
    downstream check can tell. It is refused rather than lowered because the
    honest lowering (`strlen(s) == 0`, which is exactly what `len` already
    does) is not available at this site: `not` here is a CBZ on a value in a
    register, and the kind of the expression that produced it is not
    available. The condition sites — `if s:`, `while s:`, `s and k` — have the
    same defect and are NOT fixed by this; see
    bugs/FORMAL_string_value_model.md for the count and the next step.
    """
    if op not in STRING_ARITHMETIC_UNARY_OPS and op != "not":
        return None
    if not string_operand_is_string(kind):
        return None
    if op == "not":
        return (
            f"`not {spelled_operand}` is refused because {spelled_operand} is "
            f"a string. A string on this path is a bare `char *` and a pointer "
            f"is never zero, so this test is FALSE for every string — including "
            f"the empty one, which is what Python calls falsy. Measured on both "
            f"backends: `not \"\"` returned 0 where Python returns 1. The "
            f"answer is knowable (`len({spelled_operand}) == 0`, which is a "
            f"`{STRING_LENGTH_SYMBOL}` and nothing else) but not HERE, because "
            f"`not` tests a value already in a register and this site cannot "
            f"see what produced it. Write `len({spelled_operand}) == 0`")
    return (
        f"unary {op!r} is refused on a string. A string on this path is a "
        f"bare `char *`, so {op!r} is an integer operation on an ADDRESS, and "
        f"it builds, runs and returns a number the source never wrote — "
        f"`~s` measured 8881076 on arm64 and 3236815 on x86-64 for the same "
        f"source. See string_binary_refusal for the two-operand form of this")


# ── `in` / `not in` on a string haystack ──────────────────────────────────
#
# The measured state of this, on the tree this was written on, on BOTH
# backends: `if "ell" in s:` where `s = "hello"` terminated the process with
# SIGBUS. Not a wrong answer — a crash — and the two architectures agreed on
# that much, which is the only good news in it. The cause is the same one as
# everywhere else in this section: the haystack is a `char *`, and the
# membership path had no string case for a haystack that is not a syntactic
# literal, so it read the first eight bytes of the CHARACTERS as a blob count
# and walked off the end of the mapping. x86-64 had no string case at all, so
# `"bc" in "abcd"` scanned the interned bytes as a blob; where that did not
# fault it returned FALSE, which is a wrong answer rather than a crash.
#
# So this is a libc call, on both backends, and the same libc call `find`
# already makes:
#
#     "ell" in s        ->   strstr(s, "ell") != NULL
#     101 in s          ->   strchr(s, 101)     != NULL
#
# The argument order of `strstr` is the whole method and it is the reason this
# is a table rather than a one-liner in a backend:
# `strstr("bc", "abcabcabc")` is a well-defined NULL, so getting it backwards
# does not crash, does not look wrong in the image, and returns FALSE for every
# haystack that contains its needle — which is every real use of `in`. It is
# `strstr(HAYSTACK, NEEDLE)`.
#
# `strchr` rather than a hand-written byte loop, for the reason `strspn` replaced
# the `lstrip` loop: it IS the algorithm, it cannot be half-right, and there is
# then nothing to keep in step between two architectures. `strchr` was checked
# to BIND on both backends before being relied on here (the x86-64 `strcmp`
# observation in bugs/FORMAL_string_value_model.md is why that is worth a
# measurement rather than an assumption): with `STRING_COMPARE_SYMBOL` pointed
# at it, a program that calls it ran to completion and returned a non-NULL
# pointer on arm64 and on x86-64.
STRING_SEARCH_SYMBOL = "strstr"
STRING_BYTE_SEARCH_SYMBOL = "strchr"

# The two shapes `in`/`not in` takes when the haystack is a string. Which one
# is decided by the NEEDLE's kind, because that is what decides the libc call.
STRING_MEMBERSHIP_SUBSTRING = "strstr"   # needle is a char *  → strstr
STRING_MEMBERSHIP_BYTE = "strchr"        # needle is an int    → strchr


def string_membership_lowering(left_kind, right_kind) -> str | None:
    """How `needle in haystack` lowers when the haystack is a string, or None.

    None means "not a string membership" and the caller keeps whatever it did
    before, which for a list/tuple/dict haystack is the blob scan.

    The needle decides the call and nothing else does. A string needle is
    `strstr`; a byte needle is `strchr`. An unclassified needle (None kind) is
    NOT treated as a byte: `int in str` and `str in str` are different
    questions, and guessing which one was meant is how a membership test comes
    to answer the wrong one. An unclassified needle is left to the caller,
    which for a haystack that is a string means the blob scan — so this
    function returning None for it is deliberate, and the backends' own
    refusal for an unusable haystack is what the reader sees.

    THE BYTE CASE HAS AN EDGE, and it is the reason this is a table and not a
    two-line call. `strchr(s, 0)` returns a pointer to the terminating NUL, so
    it is non-NULL, so a plain `!= NULL` would make `0 in "abc"` TRUE. Python
    says FALSE, and on this representation it is certainly false: the only NUL
    in a string is the one that ends it. The backends therefore have to test the
    byte against zero before the call, and the test is one instruction in front
    of it on both.
    """
    if not string_operand_is_string(right_kind):
        return None
    if string_operand_is_string(left_kind):
        return STRING_MEMBERSHIP_SUBSTRING
    if left_kind == INT_KIND:
        return STRING_MEMBERSHIP_BYTE
    return None


def string_index_refusal(base_kind, index_kind,
                          spelled_index: str) -> str | None:
    """Why `s[i]` cannot be lowered when `i` is itself a string, or None.

    The same class as everything else in this section, one level down: the
    subscript on a string is `s + i` on a bare `char *`, so a string INDEX
    makes it integer addition of two addresses. Measured on the tree this was
    written on, on BOTH backends, for `s = "abc"; t = "bc"; printf("%d", s[t])`:

        arm64   67          0x43 — the low byte of a text-section address
        x86-64  SIGSEGV     the sum of two addresses, dereferenced

    An address's low byte is the worst of the fabricated numbers in this file
    because it is small, printable and plausible: 67 reads like a character
    code, and a reader checking the output would have no reason to doubt it.

    NOT the same refusal as `string_operand_is_string(base_kind)` being false:
    this is about the INDEX. A string base with an integer index is `s + i`,
    which is real C pointer arithmetic and is lowered, giving the byte at that
    offset — see the `s[0]` case in bugs/FORMAL_string_value_model.md for why
    that byte rather than a one-character String is a recorded divergence
    rather than a refusal.
    """
    if not (string_operand_is_string(base_kind)
            and string_operand_is_string(index_kind)):
        return None
    return (
        f"`{spelled_index}` cannot index a string on this path: a string here "
        f"is a bare `char *`, so the subscript is `s + i` — integer addition of "
        f"two addresses when the index is a string too. Measured on both "
        f"backends: `printf(\"%d\", s[t])` printed 67 on arm64 (the low byte of "
        f"a text-section address) and segfaulted on x86-64. Use "
        f"`s.find({spelled_index})`, which is lowered as a `strstr`, or index "
        f"with an integer offset, which is the pointer arithmetic this path "
        f"does have")


def spelled(expr) -> str:
    """`expr` as the source spells it, for a diagnostic that quotes it.

    Lives here rather than in either backend because a refusal has to be able
    to say WHICH operand it is about — `len(m)` and `len(k)` are different
    problems and a message that names neither sends the reader to look at the
    whole function — and the two backends would otherwise spell it two ways
    and a diagnostic would match on one architecture and not the other.

    Deliberately an approximation: a chain is spelled out, and anything this
    does not have a shape for is named by its node type, which is the same
    fallback `_dotted` uses for a callee it cannot flatten.
    """
    if isinstance(expr, F.StringLiteral):
        return repr(expr.value)
    if isinstance(expr, F.IdentExpr):
        return expr.name
    if isinstance(expr, F.MemberExpr):
        parts = []
        node = expr
        while isinstance(node, F.MemberExpr):
            parts.append(node.member)
            node = node.obj
        parts.append(spelled(node))
        return ".".join(reversed(parts))
    if isinstance(expr, F.CallExpr):
        callee = _flat_callee(expr)
        return f"{callee}(...)" if callee else f"{type(expr).__name__}(...)"
    return type(expr).__name__


def string_has_static_storage() -> bool:
    """True when a string value's BYTES outlive the function that made it.

    Always True, and it is a function rather than a constant so that the
    question has a name at the place the answer is needed. The reasoning is in
    the section comment above: every string on this path is a literal interned
    into `__TEXT,__text` or an interior pointer into one, so its storage
    duration is static.

    WHY IT IS HERE, and who it is for: the frame-lifetime analysis in
    `formal/build.py` refuses a value that is the address of a frame when that
    value is returned, stored in a container, or handed to a callee whose
    meaning this path cannot see — and it reaches that rule for `String` and
    `StringSlice`, because the stdlib declares them as multi-field structs
    (three slots each) and wave 3's by-reference receiver makes a local bound
    from their constructor a frame address. 16 files in the stdlib sweep are
    refused by exactly that rule, and the message it prints — "the receiver of
    a multi-field struct is the ADDRESS of a frame of 8-byte slots that
    belongs to the function which created it" — is a FALSE STATEMENT about a
    value whose bytes are in the image's read-only text section and are still
    there after every function has returned.

    So: the rule is sound for a struct whose fields live in a frame, and
    unsound as applied to a `char *` to static bytes. The position half of
    that analysis (which argument positions a callee can be trusted with) is
    not this module's; this predicate is the string half of the answer, stated
    where both sides can read it. A reproducer, on both backends:

        struct String:                      # three fields, as the stdlib has it
            var _ptr_or_data: Pointer[UInt8]
            var _len_or_data: Int
            var _capacity_or_data: Int
        def make():
            s = String()
            s._len_or_data = 5
            return s                        # REFUSED: "a String receiver is
        def main(n):                        # returned from the function that
            return make().size()            # created it"

        def make():                         # the same program with the string
            s = "  hi".lstrip()             # kept as a char *:
            return s                        # BUILTS, and prints [hi]
        def main(n):
            printf("[%s]\\n", make())
    """
    return True


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


def value_method_refusal(method: str, receiver_kind, dotted: str, *,
                         receiver_is_fd=None, receiver_shape=None) -> str | None:
    """Why `recv.method()` cannot be lowered here, or None when it can.

    Shared by both backends so the two architectures cannot disagree about
    which method calls are supported — the same rule the struct field-count
    refusal follows, and the reason this text lives in the model rather than
    being spelled twice.

    `receiver_kind` is what ValueKinds says the receiver holds, or None when
    the source does not say. It is REQUIRED for every string method.

    `receiver_is_fd` and `receiver_shape` are the two facts the KIND cannot
    carry, and both are per-backend because both are flow facts: whether the
    receiver is a file descriptor (tracked where it is bound, since `open(2)`
    is the only thing on this path that produces one), and where the receiver
    came from (a name, a frame slot, a literal, a call result). The DECISION
    of what each of those permits is here; only the facts are the backend's.

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
    return _shape_guarded_refusal(method, receiver_kind, dotted,
                                  receiver_is_fd, receiver_shape)


# ── What a value-shaped method means, PER RECEIVER KIND ───────────────────
#
# Everything above this line is about STRING methods, and that framing is a
# trap for everything below it. The last fallback used to say "this backend
# lowers only append, close, write and the string methods …" for EVERY
# unrecognised method name, and for a receiver that is not a string that text
# is worse than useless: it reads as "add the method to the string table",
# which is exactly the mis-implementation to avoid. `ptr.value()` is 53 of the
# 76 files in the wave-4 sweep's largest finding group, and nothing about it is
# a string.
#
# A value on this path is ONE 64-bit word, so a method's meaning is a function
# of what that word holds, and the receiver's PROVENANCE says as much as its
# kind does. The five receiver shapes, and what each can honestly answer:
#
#   CHAR_P (kind `str`)  the bytes from the receiver to its NUL. The five
#       POINTER_BOUNDED_METHODS are a function of those bytes and are lowered.
#       Anything that needs to WRITE the bytes, or to know the length before
#       it can decide where the result ends, is out — see
#       LENGTH_DEPENDENT_METHODS, and the measured reason there is that a
#       literal is interned into __TEXT,__text with initprot 0x5 (read+exec).
#
#   LIST_BLOB (kind `list:K`)  a frame-allocated [count][elem…] blob, capacity
#       a compile-time bound (literal length + the count of `append` sites),
#       bounds-checked so overflow exits(1) loudly. `append` is lowered and is
#       the ONLY honest one: every other list method either writes the count
#       downwards (`pop`), needs a length to decide anything (`__contains__`),
#       or returns a new blob whose size nothing knows at compile time.
#
#   FRAME_ADDRESS  a multi-field struct, which on this path is the ADDRESS of
#       an out-of-line frame of 8-byte slots. A method on it is a method of a
#       type this model does not know, and D2 owns the field derivation. The
#       dominant stdlib case is a `Some[Writer]`, and the trap is specific and
#       worth writing down: `writer.write_string(s)` looks like the `write`
#       that IS lowered, and aliasing it would pass a FRAME ADDRESS as a file
#       descriptor. The C library answers EBADF, the program continues, and
#       the output is missing rather than wrong-looking.
#
#   PLAIN_WORD  an int, or a bool, or a float-truncated-to-int. The only
#       honest method is one that is the IDENTITY on a word, and that needs a
#       kind that says "this word is a bool" — which the kind model does not
#       have, because an unannotated word is an int (see the note on kinds)
#       and cannot be told apart from one.
#
#   DEREFERENCE_TARGET  a word that is an ADDRESS. `value()` is not an
#       identity here, it is a LOAD, and a load is not one instruction on this
#       path: see DEREFERENCE_METHODS for the three things a load needs and
#       this model has none of.
#
# The last two rows are why DEREFERENCE_METHODS and UNWRAP_METHODS below are
# separate tables. `Pointer.value()` and `Optional.unsafe_value()` are spelled
# alike and mean opposite things — one follows an address, the other asks which
# of two words was the empty one — and a model that grouped them by spelling
# would implement one of them as the other.

# The receiver kind each already-lowered value method REQUIRES, and the words
# to use when the receiver is something else. `append` is deliberately absent:
# its guard is in the backend, where `_scan_list_caps` has the function in hand
# and can compute the capacity, and a name the scan drops refuses there with a
# message about capacity rather than about kind. This table is the other half
# — `write` and `close`, which had NO guard at all.
#
# Measured, not assumed. `write` lowers to the C library's
# `write(fd, s, strlen(s))` and `close` to its `close(fd)`, and the
# docstrings said "the receiver of a file method IS a descriptor" because
# `open(...)` already lowers to the C library's `open(2)`. That is an
# assumption ABOUT THE SOURCE, and nothing checked it. On the pre-change tree
# all four of these BUILT on both architectures and each one passed something
# that is not a descriptor as fd:
#
#     s = "hello"; s.write("x")   # fd = a __TEXT,__text address
#     k = 7;      k.write("x")    # fd = 7
#     p = P();    p.write("x")    # fd = a frame address   (P is a struct)
#     xs = [1,2]; xs.write("x")   # fd = a frame address   (xs is a blob)
#
# None of them faults. `write(2)` on a bad descriptor returns -1, which
# nothing here checks, so the program runs, prints nothing, and exits 0. A
# silently-wrong lowering is the outcome this table exists to stop.
VALUE_METHOD_RECEIVERS = {
    "write": ("a file descriptor", "open(...) on this path, which lowers to "
                                  "the C library's open(2)"),
    "close": ("a file descriptor", "open(...) on this path, which lowers to "
                                   "the C library's open(2)"),
}

# A DEREFERENCE, not an identity. `UnsafePointer.value()` in Mojo returns the
# pointee, so on this path it would be a load from the address in the receiver
# — and a load is not one instruction here, for three separate reasons, each of
# which alone is enough to refuse:
#
#   1. THE POINTEe's TYPE decides the load. `Pointer[UInt8]` is one byte and
#      `Pointer[SIMD[dtype, 4]]` is four words, and neither is an 8-byte load.
#      The width and signedness come from `Scalar[T]`, and NOTHING in this
#      value model records a pointer's pointee: `Pointer` is in
#      IDENTITY_TYPE_CTORS, so `ptr` is an opaque word and the model cannot
#      even name the question. Teaching it to would be a pointer value model.
#   2. An 8-byte load is not a safe over-read of a smaller object. Reading
#      8 bytes at the address of a 1-byte object whose page ends there faults
#      (SIGBUS on the next page) — and `std/os/env.mojo`'s `ptr.value()` is
#      `_CPointer[UInt8]`, so the under-read is not hypothetical.
#   3. A STRUCT's value on this path is a frame ADDRESS, not memory
#      contents, so for `Pointer[SomeStruct]` there is no image at the address
#      to load at all. One word cannot hold a struct.
#
# 53 of the 76 files in this group are this one method (`std/os/env.mojo`'s
# `ptr.value()`), which is why the refusal is this specific and not the old
# blanket one. Wave 2's B5 correctly flagged that treating the characterised
# group as string methods would have been catastrophic; this is why.
DEREFERENCE_METHODS = {
    "value": "is a DEREFERENCE on this path, not an identity: it is a load "
             "from the address the receiver holds, and a load here is not one "
             "instruction. Its width and signedness come from the pointee's "
             "type, and nothing in this value model records a pointer's "
             "pointee (Pointer is an opaque word — see IDENTITY_TYPE_CTORS), "
             "so an 8-byte load would be the only thing this could emit: that "
             "over-reads a UInt8 pointee by seven bytes and can fault on a "
             "page boundary, and for a struct pointee there is nothing at the "
             "address to load, because a struct's value on this path is a "
             "frame ADDRESS. Answering it needs a pointer value model that "
             "records the pointee, which is a model change shared by both "
             "backends and the Lean proof",
    "unsafe_value": "is the same dereference under a second name (Mojo spells "
                    "the unchecked read of an UnsafePointer `unsafe_value`), "
                    "so see value",
}

# An OPTIONAL UNWRAP — the opposite of a dereference. The question is not what
# is at the address but WHICH OF TWO WORDS was the empty one, and on this path
# there is no way to tell. `self.step = None` and `self.step = 5` are both
# stores of one 64-bit word into one frame slot; `None` is emitted as the
# integer 0 (see the IdentExpr arm in each backend's `_emit_expr`), so the
# unwrap would have to treat 0 as empty and would then be wrong about
# `Some(0)` — a silent wrong answer on a program that computes a different
# number. There is no niche, no discriminant and no tag word on this path.
#
# This is the SHAPE the wave-3 by-reference work exposed, and it is worth
# separating from the dereference above because the receiver is not a word that
# happens to hold an address: `self.step` is a FRAME SLOT, so this is a method
# on a value read out of another function's frame, and the frame's field list
# is what says the slot is an Optional at all. 20 of the 76 files are this one
# method, all of them blocked behind `std/builtin/builtin_slice.mojo`.
#
# The fix is a representation for Optional (a reserved sentinel word, or a
# tag), which is a value-model change and NOT a lowering of this call.
UNWRAP_METHODS = {
    "or_else": "is an Optional unwrap: it answers by knowing which of two "
               "words was the empty one, and on this path there is no way to "
               "know. None and a value are both one 64-bit word in one frame "
               "slot, and None is emitted as the integer 0, so treating 0 as "
               "empty would be wrong about Some(0) — a silent wrong answer on "
               "a program that computes a different number. There is no niche, "
               "no discriminant and no tag word here. Answering it needs a "
               "representation for Optional, which is a value-model change "
               "shared by both backends and the Lean proof",
    "unsafe_value": "is an Optional unwrap (see or_else): the receiver here is "
                    "an Optional, and the word it holds is the pointer, not "
                    "the value",
    "value_or": "is an Optional unwrap; see or_else",
    "or": "is an Optional unwrap; see or_else",
}

# A method on a WRITER, which is a multi-field struct and therefore a frame
# address on this path — NOT a file descriptor. This table exists because
# `write_string` is the single most tempting name in the tree to add next to
# the `write` that IS lowered, and adding it would be the catastrophic
# mis-implementation: `write` is honest only because `open()` makes its
# receiver a descriptor (see VALUE_METHOD_RECEIVERS), and a `Some[Writer]` is
# not one. The 317 `writer.write(` sites in the stdlib are all of this shape.
WRITER_METHODS = {
    "write_string": "is a method on a Writer — a multi-field struct, so on "
                    "this path the receiver is the ADDRESS of a frame of "
                    "8-byte slots, not a file descriptor. It is not the `write` "
                    "that is lowered: that one is honest only because "
                    "open(...) makes its receiver a descriptor, and nothing "
                    "here establishes that a Writer is one. Lowering it as a "
                    "write would pass a frame address as fd(2): the syscall "
                    "returns EBADF, nothing checks it, and the program's "
                    "output is missing rather than wrong-looking",
    "write_bytes": "is a method on a Writer; see write_string",
    "write_t": "is a method on a Writer; see write_string",
    "write_repr": "is a method on a Writer; see write_string",
    "flush": "is a method on a Writer; see write_string",
}

# An MLIR builtin dunder. `__mlir_bool__` IS implementable — a Bool is a word
# holding 0 or 1 on this path, because every source of one is emitted as
# `mov #1`/`mov #0` (see the BoolLiteral and True/False arms of each backend's
# `_emit_expr`) and every comparison is 0/1, so the call is the same test `if`
# already performs. It is refused only because it cannot be GUARDED: `if b:`
# works on any word, so lowering it kind-blind would make `s.__mlir_bool__()` on
# a String answer `(s != 0)` — a plausible-looking 1 for a pointer. The guard
# needs a BOOL kind distinct from INT, which the kind model does not have
# because an unannotated word is an int (see the note on kinds). That is a
# deliberate deferral, not an impossibility: one file of the 76, and the fix
# is a fifth kind constant threaded through ValueKinds and both backends'
# kind oracles, where `_unify` would have to decide what a bool-and-an-int is.
MLIR_BOOL_METHODS = {
    "__mlir_bool__": "is a real builtin and is implementable as the same test "
                     "`if` already does (a Bool is a word holding 0 or 1 on "
                     "this path), but it is refused because it cannot be "
                     "GUARDED here: the kind model has no bool distinct from "
                     "int — an unannotated word is an int — so lowering it "
                     "kind-blind would make it answer `(receiver != 0)` on a "
                     "char * too, which is a plausible-looking 1 for a "
                     "pointer. The fix is a BOOL kind, not a lowering of this "
                     "call",
}


def receiver_shape(expr) -> str:
    """Where the receiver of a method call came from, as a word for a refusal.

    The KIND says what the word holds; the SHAPE says how the program got it,
    and the two answer different "what is missing" questions. A name that is a
    parameter is a word from the caller; a frame slot is a word read out of
    another function's frame, whose field list is what would say what it
    holds; a literal is a `char *` into read-only __TEXT,__text; a call result
    is whatever that call was declared to produce.

    Shared by both backends so the two architectures cannot disagree about
    which provenance a refusal names — the same rule the method tables follow.
    """
    if isinstance(expr, F.StringLiteral):
        return "a string literal"
    if isinstance(expr, F.MemberExpr):
        return "a frame slot"
    if isinstance(expr, F.CallExpr):
        return "the result of a call"
    if isinstance(expr, F.IdentExpr):
        return "a name"
    return "an expression this path does not classify"


def is_open_call(expr) -> bool:
    """True when `expr` is a call to the bare name `open`.

    Structural, and in the model so both backends answer it identically. It is
    the only thing that makes a word a FILE DESCRIPTOR on this path: `open(2)`
    is what the C library hands one back, and nothing else here produces one.
    """
    if not isinstance(expr, F.CallExpr):
        return False
    func = expr.func
    return isinstance(func, F.IdentExpr) and func.name in BUILTIN_FUNCTIONS \
        and BUILTIN_FUNCTIONS[func.name] == "file_open"


def _shape_guarded_refusal(method, receiver_kind, dotted, receiver_is_fd,
                           receiver_shape):
    """The receiver-kind half of `value_method_refusal`, or None when honest.

    Reached only for a method that is in NEITHER string table, so everything
    here is about a receiver that is not known to be a `char *`.
    """
    # The already-lowered container methods first: `write`/`close` are honest
    # on a file descriptor and are otherwise a syscall on a wrong fd, which is
    # the more expensive of the two mistakes because it does not even fault.
    if method in VALUE_METHOD_RECEIVERS:
        want, source = VALUE_METHOD_RECEIVERS[method]
        if receiver_is_fd:
            return None
        where = f"it is {receiver_shape}" if receiver_shape else "it is a value"
        if receiver_kind is None:
            return (f"{dotted}() lowers to the C library's {method}(2), so its "
                    f"receiver has to be {want} — and {where} whose value "
                    f"this path cannot establish to be one. Lowered anyway it "
                    f"would pass whatever the word holds as a file "
                    f"descriptor, which the C library answers with EBADF: the "
                    f"program runs, writes nothing and exits 0. Bind the "
                    f"descriptor with {source} and call the method on the "
                    f"name")
        return (f"{dotted}() lowers to the C library's {method}(2), so its "
                f"receiver has to be {want}, and this one is "
                f"{receiver_shape} classified as {receiver_kind!r} — a word "
                f"that is not a descriptor. Lowered anyway it would be "
                f"passed as fd(2), which the C library answers with EBADF: "
                f"the program runs, writes nothing, and exits 0. A method of "
                f"a struct (a Writer, say) reaches here and is NOT this "
                f"call — its receiver is a frame address. Bind the descriptor "
                f"with {source}")
    if method in DEREFERENCE_METHODS:
        return (f"{dotted}() {DEREFERENCE_METHODS[method]}. Refused rather "
                f"than emitted as a call to a symbol spelled {dotted!r}, "
                f"which is what this used to do: the image built and then "
                f"died in the loader")
    if method in UNWRAP_METHODS:
        return (f"{dotted}() {UNWRAP_METHODS[method]}. Refused rather than "
                f"emitted as a call to a symbol spelled {dotted!r}, which is "
                f"what this used to do: the image built and then died in the "
                f"loader")
    if method in WRITER_METHODS:
        return (f"{dotted}() {WRITER_METHODS[method]}. Refused rather than "
                f"emitted as a call to a symbol spelled {dotted!r}, which is "
                f"what this used to do: the image built and then died in the "
                f"loader")
    if method in MLIR_BOOL_METHODS:
        return (f"{dotted}() {MLIR_BOOL_METHODS[method]}")
    if method in BUILTIN_VALUE_METHODS:
        # `append`, whose guard is in the backend: `_scan_list_caps` has the
        # function in hand and can compute the blob's capacity, and a name the
        # scan drops refuses there with a message about CAPACITY — which is the
        # thing a reader has to fix. Refusing here would be both less accurate
        # and one more thing to keep in step between two architectures.
        return None
    holds = repr(receiver_kind) if receiver_kind else "a word of unknown contents"
    return (f"{dotted}() is a method call on a value, and this backend "
            f"lowers only "
            f"{', '.join(sorted(BUILTIN_VALUE_METHODS))} (on "
            f"{_article_join(sorted({v[0] for v in VALUE_METHOD_RECEIVERS.values()}))}"
            f") and the string methods "
            f"{', '.join(sorted(POINTER_BOUNDED_METHODS))}"
            f" — the receiver is "
            f"{receiver_shape or 'a plain word'} on this path, and "
            f"{method!r} is not one of those methods of those receivers, so "
            f"adding it to either table would be a guess about what it means "
            f"on {holds}. Refused rather than emitted as a call to a symbol "
            f"spelled {dotted!r}, which is what this used to do: the image "
            f"built and then died in the loader")


def _article_join(items) -> str:
    """`['a file descriptor']` -> 'a file descriptor'; two of them read better
    joined than enumerated, and the fallback names a SET so the same word is
    not printed twice."""
    uniq = list(dict.fromkeys(items))
    if len(uniq) == 1:
        return uniq[0]
    return ", ".join(uniq[:-1]) + " or " + uniq[-1]

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
#
# A third possibility was not in that list and is the reason the default branch
# used to fire on 23 of this repository's 25 hand-off sites: **a name the
# analysis already has, classified as one it does not.** `Pointer` sat in the
# value-only set, and its text says the callee "wants the object itself … so
# what would arrive is the address `Pointer()` would then dereference as one" —
# but `Pointer` is an IDENTITY type constructor (`IDENTITY_TYPE_CTORS`), so what
# arrives is the answer, not the mistake, and `Pointer(to=stat)` over a frame is
# the one hand-off in this family that is simply correct. See
# `FRAME_ADDRESS_CTORS`.

# Calls by bare name that ASK FOR THE ADDRESS of what they are handed.
#
# DEFINED BELOW, next to `IDENTITY_TYPE_CTORS` and `STRING_TYPE_CTORS`, which
# it is derived from — see the note there. `frame_receiver_escape_refusal` is
# the only reader, and it reads the name at call time.
#
# What this does NOT make safe is a DEREFERENCE through the result, and that is
# already refused by name and for its own reasons: `DEREFERENCE_METHODS` covers
# `value`/`unsafe_value`, and it says why in terms a reader can act on (an
# 8-byte load over-reads a `UInt8` pointee, and for a struct pointee there is
# nothing at the address to load, because a struct's value on this path IS a
# frame address). So the word that escapes here is one nothing on this path
# dereferences.

# Calls by bare name that the model lowers as an operation on a value, and so
# take the VALUE rather than a pointer to it. `len` is here because it is the
# commonest one by an order of magnitude; the others are the value/type
# constructors and `origin_of`, which all ask what the object IS.
#
# The identity ADDRESS constructors are NOT here any more — see
# `FRAME_ADDRESS_CTORS` above for the measurement — and the string-producing
# identity ones (`String`, `str`, `StringLiteral`, `StringSlice`) stay, because
# they are the opposite case: the word they are handed becomes a `char *` that
# every `%s` and every string method DEREFERENCES, so handing one a frame
# address is handing printf an address to read as text.
FRAME_VALUE_ONLY_CALLS = {
    "len", "origin_of", "isinstance", "issubclass", "repr", "str", "int",
    "float", "bool", "hash", "id", "type", "String",
    "StringRef", "PointerType",
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

# Calls by bare name that reach the C library and take a VALUE of a type their
# own prototype names — a `char *`, an `int`, a count.  A separate set from the
# one above because the reason is different and both are worth saying: these do
# not read the struct's bytes, they want one of its fields, and they are
# VARIADIC in the formatting cases, so a frame address is not merely the wrong
# category — it is read by whatever conversion the format string names, and the
# program prints a number nobody wrote and exits 0.
#
# `printf` was the measured one and it is the reason this set exists: it was
# falling through to the "no definition in hand" branch, which is false (it is
# libSystem's, and it binds) in a way that would send a reader looking for a
# missing export.
FRAME_C_VALUE_CALLS = {
    "printf", "sprintf", "snprintf", "fprintf", "vprintf", "vsnprintf",
    "vfprintf", "fputs", "puts", "putchar", "putc", "strlen", "strnlen",
    "strcmp", "strncmp", "memcmp", "atoi", "atol", "atoll", "exit", "abort",
    "malloc", "calloc", "realloc", "free", "memset", "qsort", "abs", "labs",
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
    what it compiled — so this function is about the cases where the answer
    does not depend on that.

    FIVE answers, and the order is the order the question is actually decided
    in, because the first three are the ones that were being answered wrongly:

    1. an ADDRESS constructor — **not a refusal at all**, and that is the
       measurement rather than a hope (see `FRAME_ADDRESS_CTORS`);
    2. a C library entry point, which reads the struct's BYTES;
    3. a type constructor the model knows about but cannot represent, which is a
       different thing again from "a function this module does not compile" and
       used to be reported as it;
    4. a name lowered as an operation on a VALUE;
    5. everything else, which really is a name with no definition in hand."""
    who = ", ".join(struct_names) if struct_names else "this struct"
    if callee in FRAME_ADDRESS_CTORS:
        # Measured, not assumed: see FRAME_ADDRESS_CTORS. Returning None here
        # is the whole of the fix for the `_c_stat`/`Pointer(to=stat)` shape.
        return None
    if callee in FRAME_C_LIBRARY_CALLS:
        return (f"a {who} frame address is passed to {callee}(), which is a C "
                f"library entry point and reads the struct's BYTES, and the "
                f"frame is a block of 8-byte slots at `base + 8k` in DECLARATION "
                f"order. That is the C layout of a struct whose every field is 8 "
                f"bytes wide and 8-aligned, so the two coincide exactly in that "
                f"case — but the struct {callee}() knows about is the C "
                f"library's own declaration of it, with the widths and padding "
                f"from the C headers rather than from the Mojo declaration "
                f"here, and nothing on this path compares the two. So the "
                f"coincidence is per-struct and unestablished, and a mismatch "
                f"reads the wrong words and returns a number the source never "
                f"wrote")
    if callee in FRAME_C_VALUE_CALLS:
        return (f"a {who} frame address is passed to {callee}(), which is a C "
                f"library entry point and takes a VALUE of a type its own "
                f"prototype names — a `char *`, an `int`, a count — not the "
                f"struct's storage. A frame address is an address, and in the "
                f"formatting cases the argument is VARIADIC, so whatever "
                f"conversion the format string names is applied to it: "
                f"measured, `printf(\"val=%d\\n\", r)` builds, runs, prints the "
                f"frame's address as a decimal, and exits 0. Read a field out "
                f"first (`{callee}(…, r.n)`)")
    tkind = type_constructor_kind(callee)
    if tkind is not None and tkind[0] == "unsupported":
        return (f"a {who} frame address is passed to {callee}(), and {callee} is "
                f"a real type this path has no representation for at all: one "
                f"formal value is one 64-bit word, and {callee} is not one "
                f"word. That is a different fact from the frame layout, and it "
                f"is the one that stops this program — there is no argument to "
                f"give it, frame or otherwise")
    if callee in FRAME_VALUE_ONLY_CALLS or (tkind is not None
                                            and tkind[0] == "identity"):
        # The `identity` half of the disjunction is the STRING-producing
        # identity constructors — `StringSlice` and `StringLiteral`, which are
        # in neither this set nor `FRAME_ADDRESS_CTORS` and would otherwise
        # fall through to the "no definition in hand" branch, which is the
        # same misclassification one layer down: `StringSlice` is a name this
        # model compiles. What makes it a refusal is the same thing that makes
        # `String` one: the word becomes a `char *` that callers dereference.
        return (f"a {who} frame address is passed to {callee}(), which is "
                f"lowered as an operation on a VALUE: it wants the object "
                f"itself, and on this path a multi-field struct has no value "
                f"form — its receiver is a pointer to a frame of 8-byte slots, "
                f"so what would arrive is the address {callee}() would then "
                f"dereference as one. Not a missing layout: a wrong category "
                f"of argument. Give it a field (`{callee}(self.n)`) or copy "
                f"the value out first")
    return (f"a {who} receiver is passed to {callee}(), which is a name with no "
            f"definition in hand: this module's own functions are the only ones "
            f"in this image, and the symbol is unbound before the receiver's "
            f"layout is a question. A frame address would be meaningful to a "
            f"callee compiled against the same field list, but there is no such "
            f"callee here to be compiled. "
            f"bugs/FORMAL_wide_receiver_by_reference.md records the design and "
            f"what is still open about it")


# ── The three hand-off shapes the escape check refused as one ───────────────
#
# `_check_frame_escapes` used to spell all of these with the same sentence, and
# two of the three said something that is not true of the program in front of
# the reader. They are separate functions, in this file, so the two backends
# cannot answer them differently and a reader gets the one that operates.
#
# The third of those shapes — a struct CONSTRUCTOR reached with a frame address
# — is no longer here at all, and its REMOVAL is the content. It was reported
# as "a X receiver is passed to R(), which this module does not compile", false
# twice over (`structs_by_name` holds `R`, which is the only reason the argument
# is a frame address, and a struct has no body to compile), and its real
# content was one level down: a copy construction had no lowering. It has one
# now, so the diagnostic moved from "this is not a call" to "here is which of
# the three shapes this is, and here is why this one is not representable" —
# `struct_construction_plan` below, which is the one place both backends and
# the build pass read it from.


def _who(struct_names) -> str:
    return ", ".join(struct_names) if struct_names else "this struct"


def _where(position, total, kwname: str = None) -> str:
    """`in argument position 1 of 3`, or the keyword's own name.

    A keyword argument has no position to quote, and printing the index it
    happens to occupy in the concatenated `args + kwargs` list is a statement
    about the ANALYSIS's list rather than about the call — the word lands
    wherever the parameter list says it does, and a reader sent to position 2
    of a call that wrote `take(x=1, y=r)` goes looking in the wrong place."""
    if kwname:
        return f"as the keyword argument {kwname!r}"
    return (f"in argument position {position}"
            + (f" of {total}" if total and total > 1 else ""))


def frame_opaque_position_refusal(where_the: str, callee: str, position,
                                  total, struct_names, method: str = None,
                                  kwname: str = None, why: str = None) -> str:
    """A frame address in a position THIS PASS cannot establish.  Case 3.

    The honest remainder, and it is marked as a statement about the ANALYSIS
    because that is what it is: there is no declaration in hand for the
    parameter this argument lands in, so nothing here can say whether the
    callee treats that word as a frame address.  Every shape that CAN be
    established is established instead — see `frame_holder_disagreement_refusal`
    for the one where the declaration is in hand and the two call sites
    disagree, which is a different thing and a commoner one.

    `why` names which of the ways the declaration is missing, because "this
    pass cannot see it" without the reason is the sentence this whole family
    was written to stop saying."""
    who = _who(struct_names)
    head = (f"a {who} receiver is passed to {where_the} "
            f"{_where(position, total, kwname)}, and {why}. ")
    if method:
        return (head +
                f"This is not a question about the position: a METHOD call on a "
                f"value receiver is dispatched by NAME, so `recv.m(x)` carries no "
                f"type and the parameter list belongs to a declaration this walk "
                f"has not read — and the method-call rewriting runs before any "
                f"frame analysis exists, so a method it could not rewrite "
                f"arrives still spelled `{method}` with no lifted name to look a "
                f"parameter list up by. A frame address in a bare-name call IS "
                f"followed into the callee's parameter at that position, in "
                f"every position and not only the first. Measured on the shape "
                f"that IS rewritten, which shows the rule is right: `w.emit(s)` "
                f"becomes `W_emit(w, s)`, whose FIRST parameter is the receiver, "
                f"so `s` is the method's second parameter — and it is followed "
                f"there too. What closes this is the method's declaration "
                f"reaching the analysis: a receiver whose type names the struct, "
                f"so the call can be rewritten and the parameter list read")
    return (head +
            f"This is a limit of the ANALYSIS and not a fact about the program: "
            f"the frame belongs to the function that created it, that function "
            f"is an ancestor of the callee — the address reached the callee "
            f"through an active call — so a read or a write through this "
            f"parameter would be in the right place, and the missing thing is "
            f"the declaration that says so. Nothing in this image is compiled "
            f"wrong without it: the word is refused rather than followed, so "
            f"the alternative is a program that builds, runs, and returns a "
            f"number the source never wrote")


def frame_holder_disagreement_refusal(callee: str, position, param,
                                      holder_structs, holder_spellings,
                                      plain_spellings) -> str:
    """One parameter reached with a frame address at one call site and with
    something else at another.  The measured wrong answer this replaces.

    The holder fixpoint makes a parameter a holder when a call site hands it a
    frame address, and it used to do that at the FIRST position with nothing
    said about the other call sites.  So `f` below compiles `x.a` as a frame
    read, and the call `f(2, 3)` arrives with `x = 2`:

    ```
    struct R: var a: Int; var b: Int
    def f(x: Int, y: Int) -> Int: return x.a
    def main(n: Int) -> Int:
        var r = R(); r.a = 7; r.b = 8
        return f(r, 1) + f(2, 3)
    ```

    **Measured on both architectures, with nothing lifted: it builds, runs, and
    dies with SIGSEGV (exit 139)** — the word 2 is not a frame address and
    `x.a` loads eight bytes from wherever 2 points.  This is a use-after-free's
    sibling, and it is in the shipped tree, at the FIRST position, before this
    change existed: the rule the family was written for was never the thing
    that was wrong.

    So a parameter's being a holder is a property of the WHOLE IMAGE, not of
    one call site, and this refusal is what makes that visible.

    Phrased from BOTH sides and naming both, because either call site can be
    the one the reader is standing at, and a message that names the wrong one of
    the pair is the same defect as a message that names the wrong reason: it
    sends the reader to a call that is fine.  The spellings are the source's
    own, so the pair is visible without re-running anything.
    """
    who = _who(holder_structs)
    return (f"{callee}() takes a {who} receiver at argument {position} — "
            f"{param!r} — at {' and '.join(holder_spellings)} here, and "
            f"something that is not a frame address at "
            f"{' and '.join(plain_spellings)}. One parameter, two kinds of "
            f"value: {callee}() is compiled with {param!r} as a frame holder, "
            f"so a field read through it is a load at `base + 8k` — and at the "
            f"other call site there is no frame there at all. Measured on both "
            f"architectures with nothing lifted: the two-call-site shape builds, "
            f"runs, and dies with SIGSEGV (exit 139). Give {param!r} one kind "
            f"of value at every call site — pass the frame address everywhere, "
            f"or nowhere")


def frame_return_refusal(owner, received: bool, struct_names) -> str:
    """A frame address RETURNED.  `owner` is the struct whose method the
    returning function is, or None for a plain function; `received` says the
    frame was NOT built here.

    "Returned from the function that created it" is true for a frame a function
    built and false for one that arrived as a PARAMETER, and the second is the
    larger half of this family: the holder fixpoint makes a callee's parameter a
    holder — in every position since the position rule was split out of this
    one — so `def fwd(r): return r` in a program whose object was made by `main`
    was reported as a return from the creator. The refusal is right — nothing
    here establishes that the creator is still on the stack — and the sentence
    was naming the wrong function, which sends the reader to look at `fwd` for a
    construction that is in `main`.

    Which is why nothing here says "first parameter" any more.  It said that
    because the fixpoint only followed index 0, and it became false the moment
    the fixpoint followed every position: `def stash(x, y): return y` receives
    the frame as its SECOND parameter, and a message naming the first one
    points the reader at a parameter the source does not use.

    The hazard is measured, not asserted, and it is a use-after-free rather than
    a wrong number in the shape that matters: with the creator one frame
    deeper, `def stash(x, y): return y` called as `outer(1)`, the program built,
    ran, and returned **10 on arm64 and 0 on x86-64** where the source says 7 —
    the bytes the address names had been reused, and the two architectures
    disagreed about what was in them."""
    who = ", ".join(struct_names) if struct_names else "this struct"
    tail = (f" Returning the address hands the caller a pointer into a frame "
            f"whose lifetime this pass cannot follow, and the failure is a "
            f"wrong number rather than a crash: the bytes get reused and the "
            f"read returns whatever is in them now. Measured with this check "
            f"removed: the same shape returns 10 on arm64 and 0 on x86-64 "
            f"where the source says 7 — a use-after-free, and a two-backend "
            f"disagreement about what the reused bytes held. "
            f"Return a field (`return self.n`) or a copy of the value, which "
            f"is the same program with a lifetime this analysis can see")
    if received and owner:
        return (f"a {who} receiver is returned from a method of {owner}, which "
                f"did not create the frame — it received the address as its "
                f"receiver, so the function that DID create it is "
                f"somewhere up the call chain and nothing here establishes that "
                f"its frame is still there." + tail)
    if received:
        return (f"a {who} receiver is returned from a function that did not "
                f"create it: the address arrived as one of its parameters, so "
                f"the function that built the frame is this function's CALLER "
                f"or an ancestor of it, and "
                f"nothing here establishes that the caller's frame is still "
                f"there when the caller reads the value this return produces." +
                tail)
    return (f"a {who} receiver is returned from the function that created it "
            f"on this path: the receiver of a multi-field struct is the ADDRESS "
            f"of a frame of 8-byte slots that belongs to the function which "
            f"created it, and that frame is reclaimed when the function "
            f"returns, so the address the caller would dereference names "
            f"reclaimed stack." + tail + ". "
            f"bugs/FORMAL_wide_receiver_by_reference.md records the design and "
            f"what is still open about it")


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


def type_constructor_prefers_local_struct(callee_name: str, structs: dict,
                                          nargs: int) -> bool:
    """Whether THIS MODULE's own `struct N` beats `N`'s place in
    `UNREPRESENTABLE_TYPE_CTORS`.

    `UNREPRESENTABLE_TYPE_CTORS` is a hand-kept list of NAMES, and a name in it
    was refused outright — "constructing DType has no representation on this
    path" — without anybody asking what the file being compiled says about
    `DType`.  In a file that DECLARES `struct DType`, that declaration is the
    only thing in hand that says what the name means, and the hand-kept list
    was overriding it.  That is the defect: the list is a statement about types
    this path cannot represent *abstractly*, and a struct of one field is a
    plain word, which is the most representable thing there is.

    So the rule that was masked is the ordinary one, and ARITY is what applies
    it: a call whose argument count matches the local declaration's field count
    is a construction of that struct, and one that does not match is not — which
    leaves the name's own reading standing for every other arity, so this can
    never reclassify a call the tables already handled well.

    Two deliberate exclusions, both measured:

      * only `UNREPRESENTABLE_TYPE_CTORS` is overridden, never the identity or
        the integer tables.  `Pointer` is a struct some files in this
        repository declare AND an identity conversion, and
        `Pointer(to=stat)` over a struct's frame is the one hand-off in the
        whole family that is correct (a pointer wants the address, and a frame
        address is one).  Preferring the local declaration there would turn a
        working identity conversion into a construction, which is a change of
        MEANING rather than a change of verdict — the one direction this
        function must never go;
      * the field count must match, so `Error()` in a file that declares a
        two-field `Error` keeps the unrepresentable refusal.  That file is not
        in the corpus, and the point is that the rule does not need it to be:
        arity decides, and an unmatched call is left exactly as it was.

    Everything here is a change of VERDICT in one direction only: the
    'unsupported' branch is a refusal today, so preferring the local struct can
    turn a refusal into a lowering and can never change the meaning of a program
    that already built.

    The ZERO-ARGUMENT form is the second half of the answer, and it is the one
    that was still wrong. `S()` — no arguments — is not an arity to match
    against a field count: it is Mojo's own struct syntax, the shape
    `_emit_struct_constructor` was written for and the only one that used to
    exist. So for a name this image knows as a struct, `S()` is a construction
    of that struct and the struct's own field count decides whether it is
    representable — which is the whole of the rule everywhere else in this
    file. Left as it was, `struct DType: var _mlir_value: Int` — ONE field,
    and a formal value is one 64-bit word, so a `DType` is as representable as
    anything here — was refused with the sentence "a formal value is one 64-bit
    word, and DType is not one thing", which is false, while the identical
    program with the struct renamed built on both architectures. The arity test
    also masked the rule that actually stops the neighbouring case: `DTypeX(7)`
    is refused by the shape rule (`DTypeX(...) takes no arguments on this
    path`), not by anything about representability, and the name list got there
    first and said something else.
    """
    if callee_name not in UNREPRESENTABLE_TYPE_CTORS:
        return False
    st = (structs or {}).get(callee_name)
    if st is None:
        return False
    return nargs == 0 or nargs == len(struct_frame_slots(st))


# The subset of `IDENTITY_TYPE_CTORS` that ASKS FOR AN ADDRESS rather than
# yielding a `char *`: the identity constructors over an opaque word.  A
# pointer is already one word and constructing one is a no-op on this path
# (`type_constructor_kind` answers `("identity", None)`), so `Pointer(to=x)`
# yields the word it was handed — and for a multi-field struct that word is the
# frame's base address, which is exactly what a pointer to the object means.
#
# Derived, not written out, because the question this table answers is "does
# this callee DEREFERENCE its argument" and that is precisely what
# `IDENTITY_TYPE_CTORS` minus `STRING_TYPE_CTORS` already says.  A hand-written
# copy is how the two would come apart: a name added to the identity set and not
# to this one gets refused with a message whose reasoning is inverted, which is
# the defect `Pointer` was carrying.
#
# MEASURED, both architectures, rather than inferred from the tables. Three
# two-field objects in one function, each constructor's address taken with
# `Pointer(to=…)`, come out 16 and then 32 bytes apart — the frame size — so
# these are three consecutive frames and not three unrelated leftover words.
# With the frame-escape refusal in place the same program is refused, which is
# the unjustified refusal this removes.
#
# The consumer is `frame_receiver_escape_refusal`, whose FIRST branch is this
# table: a hand-off to one of these names is not a refusal at all. What it does
# not make safe is a DEREFERENCE through the result, and that is already refused
# by name and for its own reasons — `DEREFERENCE_METHODS` covers `value` and
# `unsafe_value`, and says why in terms a reader can act on (an 8-byte load
# over-reads a `UInt8` pointee by seven bytes and can fault on a page boundary;
# for a struct pointee there is nothing at the address to load, because a
# struct's value on this path IS a frame address). So the word that escapes here
# is one that nothing on this path dereferences.
FRAME_ADDRESS_CTORS = tuple(
    n for n in IDENTITY_TYPE_CTORS if n not in STRING_TYPE_CTORS)


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


# ── A field's DECLARED type: agree, or refuse ─────────────────────────────
#
# `struct_frame_slot_candidates` above settles WHERE a field lives, from the
# bindings of the name holding the frame.  What it cannot settle is WHAT the
# word in that slot is, and C5's named next step is that a field's declared
# type is the one thing on this path that says:
#
#     struct B: var _rng: SomeStruct    ->  self._rng.step() is a nested frame
#     var p: Pointer                    ->  self.p.value is a load at an offset
#
# Both are one lookup away from the AST, and both are the silently-wrong
# direction if the lookup is done halfway.  A frame slot holds ONE word.  So:
#
#   * concluding "this slot holds a frame address" obliges the codegen to PLACE
#     that frame — reserve it, initialize it, and put its address in the slot.
#     An unplaced frame address is a number the source never wrote, which is the
#     outcome this whole design exists to prevent, and it is WORSE than the
#     refusal it replaces because it does not fail;
#   * concluding "this slot holds a pointer" obliges the proof side to know the
#     pointee's layout, element size and address space, and nothing here does.
#     An arbitrary `p + k*size` load is a second addressing mode, which is a
#     second thing to get right on a path whose entire value is that there is
#     one.
#
# So the rule is the SAME one, deliberately: **AGREE OR REFUSE**, and this time
# over TYPES.  A declared type is used only when every binding of the name
# agrees with it.  One counter-example — a second declaration naming something
# else, a candidate struct that does not declare the field at all — and the name
# is NOT typed, the case stays refused, and the refusal says which candidate
# wanted what.
#
# `struct_frame_slot_candidates` is the pattern being copied exactly, and the
# tie-break is what makes the copy safe: **disagreement and "the type is not one
# of this unit's" both fall out of the typed set, never into it.**  An absent
# answer is the answer.  A name is treated as holding a nested frame only when
# every candidate's declaration names a struct THIS MODULE DECLARES whose
# receiver is a frame, and there is no path by which a doubtful annotation
# reaches the emitter.
#
# What the check buys, in the two directions, and both are real:
#
#   * FORWARD — `self._rng.step()` becomes a method call on a nested frame this
#     compiler placed, and its lifetime is the outer object's rather than
#     something the analysis has to argue about.  That is strictly MORE than the
#     refusal it replaces: the refusal's whole complaint was that the frame
#     belongs to whichever function built the object, and a frame we placed in
#     the outer frame's own block belongs to exactly the function the outer
#     object belongs to.
#   * BACKWARD — a field declared `List[Self.T]`, `Int32`, `SIMD[…]` or
#     `UnsafePointer[…]` is PROVABLY not a frame address of this unit, so the
#     word in the slot is a plain value and the diagnostic that describes it is
#     the value-method one.  Lifting the frame refusal on a proof is the
#     difference between "the frame layout cannot represent this" (which was
#     never true) and the refusal that is actually about the callee.

# The spelling decorations a declared type carries, stripped before its base
# name is looked up. `ref[Inner]`, `borrowed[...]`, `mut Self`, `out self` —
# none of them changes WHICH struct the annotation names, and keeping any of
# them would make `var p: ref[Inner]` disagree with `var p: Inner` when they are
# the same declaration of the same thing.  The strip happens BEFORE the type
# arguments are dropped, so `ref[Inner]` reduces through the `ref` to `Inner`
# rather than to an empty string.
_TYPE_DECORATIONS = ("ref", "mut", "out", "inout", "borrowed", "read", "owned",
                     "unsafe", "raises", "Self")


def _strip_type_args(text: str) -> str:
    """Whatever is outside the outermost `[...]` pair — the type's own name."""
    depth, cut = 0, None
    for i, ch in enumerate(text):
        if ch == "[":
            if depth == 0:
                cut = i
            depth += 1
        elif ch == "]":
            depth -= 1
    return text if cut is None else text[:cut]


def annotation_base_name(ann) -> str | None:
    """The bare type name a declared type names, or None if it names nothing.

    `List[Self.T]` → `List`, `PhiloxRandom[10]` → `PhiloxRandom`,
    `Random[Self.rounds]` → `Random`, `unsafe Pointer[Int32]` → `Pointer`,
    `ref[Inner]` → `Inner`, `Self.T` → `T`, `Int32` → `Int32`.

    The type ARGUMENTS are dropped rather than compared, and that is the safe
    direction for a specific reason: `List[Int]` and `List[String]` are different
    types but this path has ONE representation for both (a word), so treating
    them as the same base is not a lie about the value — it is a decision about
    which STRUCT the value is, and the struct is named by the base alone.  A
    base that is a struct of this unit decides a frame layout; the arguments
    decide nothing this path has a slot for.  A base that is NOT a struct of this
    unit decides nothing at all, and the caller says so.

    None is the important half, and it is returned for everything this function
    cannot reduce to a single identifier — which is the rule, stated positively
    because the cases are what matter:

      * no annotation at all (`x = 0`, a field only `__init__` assigns, a name
        from `__slots__`).  This is the untyped case the agree-or-refuse rule
        exists to detect, and it must not be confused with anything below.
      * a qualified name that is not a type-parameter access.  `ref[self._data]`
        is a reference to the type OF a field, and there is no declaration here
        that says what that is; returning `_data` would look up a struct named
        after a field.  `Self.origin` IS a type-parameter access and reduces to
        `origin`, which is a parameter and names no struct here.
      * a decoration with nothing after it (`out Self`, `mut`), and a
        function-typed declaration.

    Every one of those is the UNAGREED direction, so a doubtful annotation can
    only ever remove a name from the typed set.
    """
    if not isinstance(ann, str):
        return None
    text = ann.strip()
    # Leading markers, repeatedly: `unsafe mut Pointer`.  A marker followed by a
    # BRACKET wraps the type rather than qualifying it — `ref[Inner]` is a
    # reference TO an `Inner` — so the bracket's contents are what is left to
    # reduce, and the loop continues on them so `ref[ref[Inner]]` works too.
    changed = True
    while changed:
        changed = False
        for deco in _TYPE_DECORATIONS:
            if text == deco:
                return None
            if text.startswith(deco) and text[len(deco):len(deco) + 1] in (" ", "["):
                text = text[len(deco):].strip()
                if text.startswith("["):
                    depth, close = 0, None
                    for i, ch in enumerate(text):
                        if ch == "[":
                            depth += 1
                        elif ch == "]":
                            depth -= 1
                            if depth == 0:
                                close = i
                                break
                    if close is None:
                        return None
                    text = text[1:close].strip()
                changed = True
    # A CALLABLE type (`fn(x: Int) -> Int`) is a function pointer here and names
    # no struct, so it is the untyped direction rather than a base of `fn`.
    if "(" in text:
        return None
    text = _strip_type_args(text)
    if not text or not (text[0].isalpha() or text[0] == "_"):
        return None
    if "." in text:
        head, _sep, tail = text.rpartition(".")
        if head != "Self":
            # A qualified name this path cannot resolve to a declaration in
            # this unit — `ref[self.items]`, `module.Type`, `a.b.C`. Returning
            # the last component would look up a name the declaration never
            # wrote.
            return None
        text = tail
    if not text.isidentifier() or text in _TYPE_DECORATIONS:
        return None
    return text


def struct_field_declared_type(struct_def, name) -> tuple:
    """`(base_name, annotation)` for a field's declaration, or `(None, why)`.

    The ONE reading of a declared type, so a caller that wants to know what a
    field holds and a caller that wants to refuse a field cannot answer
    differently.

    `(None, why)` whenever there is no single declaration to read: the field is
    not declared here at all (a class that assigns its fields in `__init__`, or
    one whose storage is named by `__slots__` or by nothing but
    `self.<name>` reads in a method), or it is declared twice with two different
    annotations.  The second is a real disagreement and not a corner case: a
    class body that says `var p: Pointer` and is then handed an `Int` somewhere
    has two answers, and picking one is the whole class of bug this section is
    arranged to prevent.

    The `why` is returned rather than discarded because a reader of a refusal has
    to be able to see WHY a name was or was not treated as typed — that is the
    difference between a rule and a guess.
    """
    anns = []
    for field in struct_fields(struct_def):
        if struct_field_name(field) != name:
            continue
        for spelling in (getattr(field, "type_ann", None),
                         getattr(field.target, "type_ann", None)
                         if isinstance(field, F.AssignStmt) else None):
            if isinstance(spelling, str) and spelling.strip():
                if spelling not in anns:
                    anns.append(spelling)
    if not anns:
        return (None, f"{struct_def.name} does not declare {name!r}, so nothing "
                      f"here says what the slot holds — a class that assigns "
                      f"its fields in __init__ and declares none, and a field "
                      f"named only by __slots__ or only by a method's read of "
                      f"self.{name}, are both that shape")
    if len(anns) > 1:
        return (None, f"{struct_def.name} declares {name!r} more than once and "
                      f"the declarations disagree — {', '.join(map(repr, anns))} "
                      f"— so there is no single answer, and one of them would "
                      f"be a guess")
    return (annotation_base_name(anns[0]), anns[0])


def field_type_rows(structs, name):
    """`[(struct_name, base_or_None, annotation_or_None, why)]` per candidate.

    The evidence a refusal quotes, computed once and shared: which candidate
    declared what, and — for a candidate that cannot answer — why.  Split out
    from `frame_field_type_candidates` so the diagnostic and the decision read
    the same table rather than two walks of the same candidates that could
    disagree.
    """
    out = []
    for st in structs:
        base, ann = struct_field_declared_type(st, name)
        out.append((st.name, base, ann, None if base is not None else ann))
    return out


def frame_field_type_candidates(structs, name, decls: dict):
    """`(struct_or_None, (disagree, rows))` — the NESTED FRAME a field holds.

    The agree-or-refuse check for DECLARED types, and the exact analogue of
    `struct_frame_slot_candidates` one level in.  `structs` is the candidate
    list for the holder (the same list the slot check gets), `decls` is
    `{name: StructDef}` for the structs THIS MODULE DECLARES — the only ones
    whose frame layout this compiler could possibly place.

    A `struct_or_None` answer means: every candidate declares `name`, every
    declaration reduces to the SAME base name, that base names a struct of this
    module, and that struct's receiver is a frame.  Under those four conditions
    the slot holds the address of a frame whose layout is known, and the codegen
    PLACES it (`struct_nested_frame_fields`, `struct_frame_block_bytes`) rather
    than reading the agreed index on faith — which is the difference between
    this being a lowering and being the silently-wrong answer C5 named.

    `None` is returned in every other case, and `disagree` says which:

    * a candidate does not declare the field at all, or declares it twice with
      different annotations;
    * the candidates name DIFFERENT base types — the type-level twin of two
      layouts putting one field at two slots, and the same wrong answer at one
      remove;
    * the agreed base is not a struct of this module, or is one whose receiver
      is a value rather than a frame.

    The last two are not failures of the rule; they are the rule's OTHER
    answer, and the caller wants them separately because they go to different
    places.  `field_type_is_value` below is the accessor for that, so no caller
    has to re-derive the distinction from `rows` and get it subtly wrong.
    """
    rows, bases, have = field_type_rows(structs, name), set(), 0
    for _sn, base, _ann, _why in rows:
        if base is not None:
            bases.add(base)
            have += 1
    if not rows or have != len(rows) or len(bases) > 1:
        return (None, (True, rows))
    base = bases.pop()
    st = decls.get(base)
    if st is None or not struct_is_framed(st):
        return (None, (False, rows))
    return (st, (False, rows))


def field_type_is_value(structs, name, decls: dict) -> bool:
    """True when every candidate AGREES the field is not a frame of this unit.

    The other answer, and it is an answer rather than a failure: if every
    candidate declares the field and they all name the same base, and that base
    is not one of this module's framed structs, then the word in the slot is
    PROVABLY a plain value — an `Int32`, a `List`, a `SIMD`, a pointer, a type
    this image does not compile.  Nothing about the frame layout is in question
    any more, and a diagnostic about the frame layout is then a diagnostic about
    the wrong thing.

    It is deliberately a weaker claim than "the type is a scalar".  It does not
    need to be: the single thing a caller wants to know is whether the
    FRAME-SLOT reading is the right one, and a type this module does not
    declare settles that without settling anything else.
    """
    if not structs:
        return False
    bases = set()
    for st in structs:
        base, _ann = struct_field_declared_type(st, name)
        if base is None:
            return False
        bases.add(base)
    if len(bases) > 1:
        return False
    only = bases.pop()
    inner = decls.get(only)
    return inner is None or not struct_is_framed(inner)


def field_type_disagreement(structs, name, rows) -> str:
    """Why a field's name was NOT typed — the diagnostic for the negative case.

    A refusal that says "the name is not typed" and stops there is a refusal
    the reader has to re-derive, and the derivation is the interesting part:
    the point of the agree-or-refuse rule is that a reader can SEE which
    candidate disagreed and with what.  So every row is spelled, and the
    candidates that agreed are listed too — a refusal that only prints the
    problem rows leaves the reader unable to tell an absent annotation from a
    contradicted one.
    """
    parts = []
    for sn, base, ann, why in rows:
        parts.append(f"{sn} declares {name!r} as {ann!r} (base {base})"
                     if base is not None
                     else f"{sn}: {why}")
    return "; ".join(parts) if parts else "no candidate declares it"


def struct_frame_block_bytes(struct_def, decls: dict,
                             depth=None) -> int:
    """Bytes one construction of this struct occupies: its frame AND its nested.

    A field whose agreed declared type is a framed struct of this module holds
    the ADDRESS of that struct's frame, and the address has to name bytes
    somebody reserved.  So the unit of allocation stops being "one frame per
    constructor site" and becomes "one BLOCK per site": the object's own frame,
    then the frames of its typed-nested fields, laid out in declaration order
    immediately above it.

    The nested frames go ABOVE the object's own slots rather than below for one
    reason, and it is the reason the proof wants: a value read out of a frame
    consults exactly one slot, and that slot's 8 bytes lie below the first
    nested byte.  A nested frame's address is therefore not a value any read of
    the object can produce, which is `Frame.frameRead_below_nested` and is what
    keeps "the callee was handed a value" and "the callee was handed a frame"
    from ever being the same word.  Placing them below would put a frame address
    inside the outer frame's own byte range and destroy that.

    Recursive, because a nested struct's own typed-nested fields need blocks
    too, and bounded by `MAX_NESTED_FRAME_DEPTH` because the declaration graph
    can be cyclic (`struct A: var b: B` / `struct B: var a: A`) and an
    unbounded block size is an emitter that hangs rather than one that refuses.
    """
    depth = MAX_NESTED_FRAME_DEPTH if depth is None else depth
    total = struct_frame_bytes(struct_def)
    if depth <= 0:
        return total
    for _name, _slot, nested in struct_nested_frame_fields(struct_def, decls,
                                                          depth):
        total += struct_frame_block_bytes(nested, decls, depth - 1)
    return total


# How deep a chain of typed-nested fields this path will place.  One is the
# real answer for every struct in this repository and the bound exists only so
# that a cyclic declaration graph produces a refusal rather than a hang; it is
# checked in `struct_nested_frame_fields` and the refusal names the cycle.
MAX_NESTED_FRAME_DEPTH = 4


def struct_fields_written_outside_init(struct_def) -> set:
    """The fields some EXECUTED method of this struct assigns to.

    `__init__` is excluded, and that exclusion is premise (B2) again: it does
    not run on this path, so an assignment there is not a write.  See
    `frame_field_premise` for why the exclusion is a stated premise rather than
    a habit.

    This is the set that decides whether a field can hold a PLACED nested frame,
    and the reason is not conservatism for its own sake.  A placed nested frame
    is sound exactly while the slot still holds it, so the only field that may
    be treated as one is a field nothing writes: a field that IS written holds
    whatever the assignment put there, and on this path a value of a multi-field
    struct is a frame address belonging to whichever function ran the
    assignment.  Treating a written field as ours is how the constructor's
    lifetime guarantee would be lost while still being claimed.
    """
    receivers = struct_receivers(struct_def)
    out = set()
    for m in struct_methods(struct_def):
        if m.name == "__init__":
            continue
        for node in iter_nodes(getattr(m, "body", None)):
            # An augmented assignment is a read AND a write, so it disqualifies
            # a field exactly as a plain one does; both node types are taken
            # here rather than only `AssignStmt` because the two have the same
            # `target` shape and treating one as read-only would leave
            # `self.inner.a += 1` looking like a field nobody writes.
            if not isinstance(node, (F.AssignStmt, F.AugAssignStmt)):
                continue
            tgt = getattr(node, "target", None)
            if isinstance(tgt, F.MemberExpr) and isinstance(tgt.obj, F.IdentExpr) \
                    and tgt.obj.name in receivers:
                out.add(tgt.member)
    return out


def struct_nested_frame_fields(struct_def, decls: dict, depth=None):
    """`[(field_name, slot, struct)]` — the fields of `st` that hold a nested frame.

    The PLACEMENT decision, and the reason a declared type is not the
    silently-wrong direction: this is the list the constructor walks to reserve
    a block per field and store each nested frame's address into its own slot.
    A declared type that this function did not place is not used, so the
    negative cases (`frame_field_type_candidates`'s `None`) cannot leak into
    the emitter.

    Three conditions, and all three are load-bearing:

      * the field is in `struct_frame_slots`, so the frame layout has a slot to
        put an address in — the same discipline `struct_frame_slot` applies;
      * every binding of the name agrees on a declared type naming a framed
        struct of this module (`frame_field_type_candidates`);
      * **nothing writes the field outside `__init__`**
        (`struct_fields_written_outside_init`).  The third is the one an early
        version of this function left out, and leaving it out is not a
        simplification: it makes a REASSIGNED field look like the constructor's
        frame, and the constructor's lifetime argument — the whole reason the
        nested frame is better than the refusal it replaces — then does not
        apply to the value actually in the slot.  Measured on the stdlib sweep,
        dropping the condition moved 164 files' verdicts, every one of them
        because ordinary code (`self._bytes = remaining`) was being refused for
        a frame the program had just replaced.

    `depth` is the recursion bound; a chain longer than it is dropped from the
    answer rather than silently truncated, which is what makes the bound a
    refusal instead of a wrong layout.
    """
    depth = MAX_NESTED_FRAME_DEPTH if depth is None else depth
    out = []
    if depth <= 0:
        return out
    written = struct_fields_written_outside_init(struct_def)
    for name in struct_frame_slots(struct_def):
        if name in written:
            continue
        nested, (disagree, _rows) = frame_field_type_candidates(
            [struct_def], name, decls)
        if nested is None or disagree:
            continue
        slot = struct_frame_slot(struct_def, name)
        if slot is None:
            continue
        out.append((name, slot, nested))
    return out


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


# ── THE THREE CONSTRUCTION SHAPES ────────────────────────────────────────
#
# `S()`, `S(a, b, …)` and `S(x)` are three different lowerings and until now
# only the first existed.  What they have in common is that all three end with
# a FRESH BLOCK whose bytes belong to the function that created it, so all
# three are confined to that function's activation and none of them can hand
# the block anywhere.  That confinement is what makes the other two
# representable, and it is the whole content of this section — so it is worth
# stating precisely, because it is the difference between the second and third
# shapes being lowerings and being wrong answers:
#
#     A block built at a construction SITE belongs to the function the site is
#     in, and `_check_frame_escapes` refuses every channel by which it could
#     leave that activation: returning it, putting it in a container, parking
#     it in another object's field, handing it to a callee in a non-first
#     parameter position.  So the object is read only while its creator is
#     still on the stack, and:
#
#       * a WORD stored into one of its slots came from a live local or
#         parameter of that same function or of an ancestor of it, so it
#         outlives the block's last read.  A frame address is the interesting
#         case of that and is ALLOWED here — which is exactly what the
#         assignment form `o.inner = i` may not be, and the difference is
#         worth naming because the two look identical in the source: `o` in
#         `o.inner = i` may be an object built by an ANCESTOR, so the slot
#         outlives `i`'s creator and the next use of `o` reads reclaimed
#         stack.  At a construction site the object is new here, so there is
#         no such ancestor-built object to be.
#
# The two per-argument checks below are the ones that argument does NOT
# survive, and each is refused by name rather than stored.

CONSTRUCTION_DEFAULT = "default"
CONSTRUCTION_POSITIONAL = "positional"
CONSTRUCTION_COPY = "copy"


def _construction_arg_spelling(arg) -> str:
    """How a refusal names the argument it is about.

    A refusal that says "an argument" when the source has four of them sends
    the reader to count them again, so the argument is named the way the
    source spells it."""
    if isinstance(arg, F.IdentExpr):
        return f"argument {arg.name!r}"
    if isinstance(arg, F.MemberExpr):
        return f"argument {_member_chain_text(arg)}"
    if isinstance(arg, F.CallExpr):
        callee = arg.func.name if isinstance(arg.func, F.IdentExpr) else "?"
        return f"the call to {callee!r}"
    if isinstance(arg, (F.ListExpr, F.DictExpr, F.TupleExpr)):
        return "a container literal"
    if isinstance(arg, (F.IntLiteral, F.BoolLiteral, F.StringLiteral)):
        # The VALUE, not the node class: `an argument of type IntLiteral` tells
        # a reader nothing they can look for in their own source, and the
        # literal's spelling is the one thing about it that is in the source.
        return f"the literal {getattr(arg, 'value', '?')!r}"
    return f"an argument of type {type(arg).__name__}"


def _member_chain_text(node) -> str:
    """`a.b.c` for a MemberExpr chain, without importing build.py's walker.

    Deliberately a second, tiny implementation rather than a shared import:
    `formal/model.py` is imported by the BACKENDS as well as the build pass and
    must not acquire a dependency on it, and a member chain is three lines.
    """
    parts = []
    while isinstance(node, F.MemberExpr):
        parts.append(node.member)
        node = node.obj
    if isinstance(node, F.IdentExpr):
        parts.append(node.name)
    return ".".join(reversed(parts))


def construction_dead_blob_refusal(name: str, field: str, arg) -> str:
    """A construction argument that is a blob belonging to a CALLEE.

    The one per-argument hazard the confinement above does not cover, and the
    reason it is a call and not a container: a container LITERAL is built here,
    in the function whose block is being filled, so it lives at least as long
    as the slot; a name was bound here or in an ancestor, so the region it
    names does too.  A CALL is neither — `List[T]()` and every other container
    constructor on this path is a bump-allocated region of the CALLEE's own
    reserved scratch, and the callee has returned by the time the store
    happens.  Storing it would give `self.<field>.append(x)` in a method a
    blob in reclaimed stack, which is premise (B1)'s hazard arrived at from a
    direction the premise's own check does not walk: `check_frame_field_blob_
    premises` looks at what a METHOD BODY writes, and this is a constructor
    argument.

    The exception is a call to a struct this path PLACES: that is a frame
    address, one word, with a lifetime the frame layout governs, and
    `_callee_is_placed_frame` is the one predicate that knows.
    """
    callee = (arg.func.name
             if isinstance(arg.func, F.IdentExpr) else "?")
    return (f"constructing {name} with {_construction_arg_spelling(arg)} as "
            f"field {field!r} is refused on this path: {callee}() is declared "
            f"to return a container, and a container on this path is a "
            f"bump-allocated region of the CALLEE's own reserved scratch, so by "
            f"the time the constructor stores it the bytes are reclaimed — and "
            f"a method reaching through the slot afterwards appends into "
            f"reclaimed stack. A container LITERAL, or a name bound here or in "
            f"a caller, is fine for exactly the opposite reason: it is built in "
            f"a function that is still running, and so is any call whose "
            f"declared return type is not a container. Build the container and "
            f"assign the field after `S()`, which is the same program with a "
            f"lifetime this analysis can see")


def construction_frame_in_value_refusal(name: str, field: str, arg,
                                        struct_names) -> str:
    """A frame address as the whole value of a ONE-WORD struct.

    The one argument kind a framed construction accepts and a one-word one
    does not, and the asymmetry is the confinement argument read from the
    other side.  A framed object has a BLOCK, and a block is confined to the
    function that built it, so a frame address parked in one of its slots is
    read only while that function is still running.  A one-field struct has no
    block: its receiver IS the field, so the word is the struct, and this path
    has no lifetime analysis for a plain word at all — it can be passed to any
    callee, stored anywhere, and laundered past every frame check on the way,
    because a name bound from a ONE-word constructor is deliberately not a
    holder.  That is the same reason `byref_refuse_frame_address_in_a_field`
    exists, one level out.
    """
    who = ", ".join(struct_names) if struct_names else "another struct"
    return (f"constructing {name} with {_construction_arg_spelling(arg)} as "
            f"field {field!r} is refused on this path: that argument is the "
            f"ADDRESS of a {who} frame of 8-byte slots, and {name} has one "
            f"field, so its whole value IS that word — there is no block "
            f"confining it to the function that built it, and a one-field "
            f"struct's value is passed around as an ordinary word, which every "
            f"frame-lifetime check here is bypassed by. Copy the value out of "
            f"the frame first (`{name}(frame.field)`), which is the same "
            f"program with a lifetime this analysis can see")


def struct_init_overloads(struct_def) -> list:
    """`[(required, optional, [names])]` per `__init__` this struct declares.

    The shapes of the struct's user-defined CONSTRUCTORS, which is a different
    question from its field list and the one that decides what `S(a, b)` means
    when `S` declares any.

    `required` counts the parameters with no default, EXCLUDING the receiver:
    `out self` is where the object is written, not something the caller passes,
    and counting it would make every arity in this file off by one.  The
    receiver is recognised by `struct_receivers`, so a class spelling it `this`
    is read the same as one spelling it `self`.

    Empty when the struct declares no `__init__` at all, and that emptiness is
    the whole of the distinction: with no `__init__`, Mojo's `S(...)` fills the
    fields in declaration order, which is what `struct_frame_slots` describes
    and what the positional construction lowers.  With one, `S(...)` calls it.
    """
    out = []
    receivers = struct_receivers(struct_def)
    for m in struct_methods(struct_def):
        if m.name != "__init__":
            continue
        names, required, optional = [], 0, 0
        for p in (getattr(m, "params", None) or []):
            pname = p[0] if isinstance(p, (tuple, list)) else p
            if pname in receivers:
                continue
            names.append(pname)
            if getattr(m, "param_has_default", {}).get(pname):
                optional += 1
            else:
                required += 1
        out.append((required, optional, names))
    return out


def construction_init_overload_refusal(name: str, overloads, got: int) -> str:
    """`S(a, b)` where `S` declares a user-defined `__init__`.

    A refusal that has to come BEFORE the arity one, because the arity
    message's claim — "a struct's fields are filled in DECLARATION ORDER and
    there is no other form" — is FALSE for this struct, and a message that is
    false about the program in front of the reader is worse than no message.

    `std/builtin/builtin_slice.mojo`'s `Slice` is the case that makes it
    concrete and it is twenty stdlib files' first blocking fact: it declares
    TWO `__init__` overloads, a two-parameter one and a four-parameter one with
    a defaulted fourth, and the corpus writes `Slice(6, len(lst))`,
    `Slice(start, end)` and `Slice(start, end, step)`.  So `Slice(6, len(lst))`
    is not a two-field construction of a three-field struct; it is a call to the
    two-parameter constructor, which assigns `self.step = None` itself.

    Which is premise (B2) again, and the honest statement of it: this path does
    not run `__init__`.  `S()` brings every field up at its class-level default
    and nothing else, so a construction with arguments is a call whose body this
    backend has not lowered — and the fix is not to make the arity message
    accommodate it but to say which constructor the source named, so the reader
    can see that the shape is a real one and that what is missing is `__init__`.

    The overload shapes are spelled because "it has a constructor" is not
    actionable and `Slice`'s two shapes are.
    """
    shapes = "; ".join(
        f"{req} required" + (f" and {opt} defaulted" if opt else "")
        + (f" ({', '.join(names)})" if names else "")
        for req, opt, names in overloads)
    return (f"constructing {name} with {got} argument(s) is a call to a "
            f"user-defined `__init__`, not a field-filling construction: "
            f"{name} declares {len(overloads)} `__init__` overload"
            f"{'' if len(overloads) == 1 else 's'} ({shapes}), and in Mojo a "
            f"declared `__init__` is what `name(...)` calls. This path does NOT "
            f"run it — {FRAME_FIELD_BLOB_PREMISE_B2} — so every field of a "
            f"fresh {name} comes up at its class-level default and a "
            f"construction with arguments names a body nothing here has "
            f"lowered. That is a real limit and not the same one as a "
            f"mismatched field count: use `{name}()` and assign the fields, "
            f"which is the same program with a representation, and see "
            f"bugs/FORMAL_wide_receiver_by_reference.md for what running "
            f"`__init__` would cost")


def construction_arity_refusal(name: str, got: int, summary: str) -> str:
    """A construction whose argument count is not this struct's field count.

    Named with both counts and the field list, because "wrong number of
    arguments" without the field list is the reader's next question and the
    field list is the answer."""
    return (f"constructing {name} with {got} argument(s) does not match its "
            f"fields ({summary}), and {name} declares no `__init__` for it to "
            f"call instead: with no user-defined constructor, a struct's fields "
            f"are filled in DECLARATION ORDER from positional arguments and "
            f"there is no other form, so this path can only place a word in a "
            f"slot it can name. Give the fields explicitly (`{name}()` then "
            f"`obj.<field> = …`), which is the same program with a "
            f"representation")


def construction_keyword_refusal(name: str, keys) -> str:
    """`S(a=1)` — a keyword form of a construction, refused rather than
    misread.

    Refused rather than read as positional, because reading it as positional
    would depend on the order the keywords happen to appear in a dict, and a
    program's meaning must not depend on that.

    It is a REAL limit and not an oversight, and it has a shape worth stating
    because the stdlib leans on it — `StringSlice(unsafe_from_ptr=p)` is the
    idiomatic spelling and 1 stdlib file reaches it as its first thing wrong.
    What would close it is decidable and is named here so the next reader does
    not have to work it out: match each keyword against
    `struct_frame_slots`, let the positionals take the remaining slots in
    declaration order, and require the two together to cover every field
    EXACTLY once — a keyword naming no field, a field named twice, and a field
    left uncovered are each a refusal with its own reason.  That is a small
    extension of what is here and it was left out of a change whose subject is
    the three positional shapes, not because it is hard.
    """
    return (f"constructing {name} with keyword argument(s) "
            f"{', '.join(repr(k) for k in keys)} is not a shape this path "
            f"lowers: {name}'s fields are filled in DECLARATION ORDER from "
            f"positional arguments, and reading a keyword as positional would "
            f"make the program's meaning depend on the order the keywords "
            f"appear in. Match the keyword against the field list instead — "
            f"each keyword naming a field, the positionals taking the rest in "
            f"declaration order, and the two together covering every field "
            f"exactly once — or pass the values positionally, or use `{name}()` "
            f"and assign the fields")


def construction_nested_slot_refusal(name: str, field: str, arg,
                                    nested_name: str) -> str:
    """A construction argument landing on a field the constructor PLACED.

    The one positional argument this path must refuse for a reason of its own.
    The slot is not an ordinary slot: `struct_nested_frame_fields` placed a
    frame in it, in the object's OWN block, and that placement is what makes
    the word in it mean anything — it is a frame address whose layout this
    compiler chose.  Storing an argument over it would leave a word in a slot
    that every reader (`self.<field>.<field>`) treats as a frame base, so a
    field read would compute an address out of a value.

    The two honest ways out are both in the message, and neither is "just store
    it": assign the field, which the write path already handles and which is
    why a written field is excluded from the placement list in the first
    place, or declare the field untyped, which takes it out of the placed set.
    """
    return (f"constructing {name} with {_construction_arg_spelling(arg)} as "
            f"field {field!r} is refused on this path: {field!r} is declared "
            f"as a {nested_name}, a struct of this module whose receiver is a "
            f"frame of 8-byte slots, so the constructor PLACED a {nested_name} "
            f"frame in that slot and in the object's own block — a word stored "
            f"over it would leave a value where every read of "
            f"`self.{field}.…` computes a frame base from it. Assign the field "
            f"after `{name}(…)`, which is the same program and is the form the "
            f"placement's own write-once rule already anticipates")


def construction_copy_source_refusal(name: str, arg, struct_names) -> str:
    """`S(x)` where `x` is a frame, but not a frame of `S`.

    The one copy that cannot be a copy, and the reason is that a copy here is a
    SLOT-FOR-SLOT copy: slot `k` of the source into slot `k` of the
    destination, which means anything only if the two layouts are the same
    layout.  A different struct is a different layout by definition, and a
    name that may be either is two layouts with no path sensitivity to say
    which — the same `struct_frame_slot_candidates` question one level in, and
    it has the same answer: agree or refuse.
    """
    who = ", ".join(struct_names) if struct_names else "another struct"
    return (f"constructing {name} with {_construction_arg_spelling(arg)} is a "
            f"COPY CONSTRUCTION and the argument is a {who} frame, not a "
            f"{name} one: a copy on this path is a slot-for-slot copy — slot k "
            f"of the source into slot k of the destination — so it is only "
            f"defined when the two layouts are the same layout. Construct "
            f"{name}() and assign the fields, which is the same program with "
            f"a representation")


def construction_copy_unrecognised_refusal(name: str, arg) -> str:
    """`S(x)` where nothing here can say what `x` is.

    The refusal that matters most in this section, because it is the one whose
    absence is a silently-wrong answer rather than a missing feature.  A copy
    needs a BASE to copy from, and on this path the only thing that says a word
    is a frame address is the holder analysis — a name bound from a framed
    struct's constructor, a copy of such a name, a method receiver, or a
    visible callee's first parameter, carried to a fixpoint.  A name outside
    that set is a plain word, and reading slot `k` of it would be reading
    whatever eight bytes the word happens to name.

    So an ABSENT answer is the answer, which is the same tie-break
    `frame_field_type_candidates` uses and for the same reason: a doubtful
    case must be able to fall out of the typed set and never into it.
    """
    return (f"constructing {name} with {_construction_arg_spelling(arg)} is a "
            f"COPY CONSTRUCTION and nothing here can say that argument is a "
            f"{name} frame: a copy needs a base to copy from, and the only "
            f"thing on this path that says a word is a frame address is the "
            f"holder analysis — a name bound from a framed struct's "
            f"constructor, a copy of one, a method receiver, or a visible "
            f"callee's first parameter. This name is none of those, so it is a "
            f"plain word, and copying slot k out of it would copy whatever "
            f"eight bytes that word happens to name. Construct {name}() and "
            f"assign the fields, which is the same program with a "
            f"representation")


def struct_construction_plan(struct_def, call, decls: dict,
                             candidates: dict, rets=None) -> tuple:
    """`(plan, refusal)` — which of the three shapes `S(...)` is, or why not.

    THE decision, in the shared model, so the two backends cannot answer it
    differently and the build pass (which refuses before either backend runs)
    and the emitters (which have to emit) read one table.  `decls` is
    `{name: StructDef}` for the structs this module declares; `candidates` is
    `formal/build.py`'s `{holder name: [StructDef, …]}` for the function the
    call is in — the recognition a copy construction needs, and the only thing
    in the compiler that can say a word is a frame address, and `rets` is
    `function_return_types`' `{name: declared return annotation}` — the
    evidence for the one argument kind that is refused, a container returned by
    a callee (`_construction_arg_is_dead_blob`).

    A `plan` is `(kind, …)`:

    | kind | payload | what the emitter does |
    |---|---|---|
    | `CONSTRUCTION_DEFAULT` | — | the existing `S()`: every field at its own default, and every placed nested frame brought up |
    | `CONSTRUCTION_POSITIONAL` | `[(field, slot)]` in DECLARATION ORDER, one per argument | evaluate each argument, store it at `base + 8·slot` |
    | `CONSTRUCTION_COPY` | the slot count | evaluate the source, then `n`-slot copy into the fresh block |

    `slot` is `None` in the positional payload exactly when the struct is a
    one-word VALUE rather than a frame: there the argument is not stored at
    all, it IS the result, which is the same statement as "stored at slot 0 of
    a zero-byte frame" and is the only reading of `S(x)` that does not invent
    storage.

    The refusals, each with its own message and its own reason, are in the
    functions above; a reader who wants to know which construct is being
    refused can tell from the first clause of each.
    """
    name = struct_def.name
    decls = decls or {}
    candidates = candidates or {}
    args = list(getattr(call, "args", None) or [])
    kwargs = list(getattr(call, "kwargs", None) or [])
    slots = struct_frame_slots(struct_def)
    if kwargs:
        return (None, construction_keyword_refusal(
            name, [k for k, _v in kwargs]))
    if not args:
        # The existing shape.  Deliberately NOT re-decided here: `S()`'s
        # refusal for a non-literal default belongs to
        # `struct_frame_representable` / `struct_default_word` and has its own
        # message, and a second copy of the decision is a second thing to keep
        # in step with the first.
        return ((CONSTRUCTION_DEFAULT,), None)
    # A DECLARED `__init__` outranks everything below, and it has to: with one,
    # `S(a, b)` is a call to it, so every message underneath — the arity one
    # included — is describing a construct the source does not contain.
    # `Slice(6, len(lst))` against a three-field `Slice` is the case, and it is
    # twenty stdlib files' first blocking fact.
    overloads = struct_init_overloads(struct_def)
    if overloads:
        return (None, construction_init_overload_refusal(
            name, overloads, len(args) + len(kwargs)))
    if not struct_is_framed(struct_def):
        # Zero or one field: the whole value is one word.  Zero fields has
        # nowhere to put an argument at all, which is an arity refusal with
        # the field list saying so.
        if len(slots) != 1:
            return (None, construction_arity_refusal(
                name, len(args), struct_field_summary(struct_def)))
        only = slots[0]
        for arg in args:
            if _construction_arg_is_dead_blob(arg, rets):
                return (None, construction_dead_blob_refusal(name, only, arg))
            src = _frame_source_structs(arg, candidates)
            if src:
                return (None, construction_frame_in_value_refusal(
                    name, only, arg, [s.name for s in src]))
        return ((CONSTRUCTION_POSITIONAL, [(only, None)]), None)

    # A FRAMED struct.  One argument that is a recognised frame of THIS struct
    # is a copy, and it is checked before the arity rule because arity is what
    # makes it look wrong: `R(r)` on a two-field `R` is not a one-field
    # construction, it is a copy of a two-field object.
    if len(args) == 1:
        src = _frame_source_structs(args[0], candidates)
        if src is not None:
            if len(src) != 1 or src[0] is not struct_def:
                return (None, construction_copy_source_refusal(
                    name, args[0], [s.name for s in src]))
            return ((CONSTRUCTION_COPY, len(slots)), None)
        if isinstance(args[0], F.IdentExpr):
            # A name, and NOT a holder: a plain word.  `S(x)` with a plain word
            # is an arity error on a multi-field struct and saying so is the
            # whole content — but the copy reading is the one a reader will
            # have in mind, so it is named as such rather than left to be
            # inferred from a count.
            return (None, construction_copy_unrecognised_refusal(name, args[0]))
    if len(args) != len(slots):
        return (None, construction_arity_refusal(
            name, len(args), struct_field_summary(struct_def)))
    placed = {field: child.name
              for field, _slot, child in struct_nested_frame_fields(
                  struct_def, decls)}
    plan = []
    for arg, field in zip(args, slots):
        if field in placed:
            return (None, construction_nested_slot_refusal(
                name, field, arg, placed[field]))
        if _construction_arg_is_dead_blob(arg, rets):
            return (None, construction_dead_blob_refusal(name, field, arg))
        plan.append((field, struct_frame_slot(struct_def, field)))
    return ((CONSTRUCTION_POSITIONAL, plan), None)


def _construction_arg_is_dead_blob(arg, rets=None) -> bool:
    """Whether a construction argument is a container belonging to a CALLEE.

    One predicate, because it is one fact and the two call sites were two
    copies of a three-line test.  It is a CALL, and among calls only the ones
    whose DECLARED RETURN TYPE is a bump-allocated region: a function that says
    it returns `Int` puts an integer in the slot, whatever it did internally,
    and a function that says it returns a `List` puts a region of ITS OWN
    reserved scratch in the slot, and that scratch is reclaimed the moment it
    returns.

    The declared return type is the whole of the evidence, and the cases are
    the three this path can tell apart:

      * a container type — refused, by name;
      * any other type, INCLUDING no type at all — allowed.  A function that
        declares nothing returns whatever its body returns, and a
        `-> Int`-shaped declaration is the ordinary case (`scale(2)` in
        `constr_positional_expression_arguments`), so refusing every call would
        refuse essentially every positional construction in a real program.  An
        absent answer has to be the PERMISSIVE one here, and that is the
        opposite tie-break from the copy construction's on purpose: a wrong
        word in a slot is a value the source did not write, while a missed blob
        is only reachable if some method later appends through the slot — and
        that path is refused on its own terms today (`list.append()` needs the
        capacity to be known where the list is built, and a slot is not a list
        literal).  So the residual is real and it is stated rather than
        guessed at in either direction: it is the same gap premise (B1) has
        about a bare name, and what closes it is the VALUE KIND of a call's
        result, which is `ValueKinds`' question and not a re-derivation to be
        smuggled in here;
      * a call to a struct this path PLACES — a frame address, one word, with a
        lifetime the frame layout governs.  Not a container and not refused.

    A container LITERAL and a name are not in this function at all: a literal
    is built by the function whose block is being filled and a name was bound
    in that function or an ancestor, so in both cases the region outlives every
    read of the slot.  `construction_dead_blob_refusal` is where that argument
    is spelled out for the reader.
    """
    if not isinstance(arg, F.CallExpr) \
            or not isinstance(arg.func, F.IdentExpr):
        # `arg.func` is a bare name or it is not a call this table can say
        # anything about: `List[Self.T]()`, `Self.T[…]()`, `a.b()` and
        # `f()[0]()` all land here, and a subscript callee is not a name in
        # `rets` — it is a type or an expression whose result this path does
        # not follow.  Not a blob, because nothing here knows that it is one.
        return False
    if _callee_is_placed_frame(arg.func.name):
        return False
    return return_type_is_blob((rets or {}).get(arg.func.name))


# The annotations that name a BUMP-ALLOCATED REGION on this path — the types
# whose value is a word pointing into the creating function's own reserved
# scratch, as opposed to a word that means something on its own.  `String` and
# its relatives are deliberately NOT here: a string literal has static storage
# duration, so a string is the one pointer on this path with no lifetime
# problem at all, and treating it as a blob would refuse the most common
# argument in the corpus.
BLOB_TYPE_NAMES = frozenset({
    "List", "Dict", "Set", "Tuple", "Optional", "InlineArray", "StaticTuple",
    "Array", "StringRef",
})


def return_type_is_blob(annotation) -> bool:
    """Whether a declared return type names a bump-allocated region.

    `List[Self.T]` and `unsafe Pointer[Int32]` both reduce through
    `annotation_base_name`, so the type ARGUMENTS are dropped rather than
    compared — the same reading `annotation_base_name` gives a field's declared
    type and for the same reason: the base decides which KIND of thing the word
    is, and the arguments decide nothing this value model has a slot for.

    False for an absent or unreadable annotation.  That is the permissive
    direction and `_construction_arg_is_dead_blob` says why, at length, because
    a reader who finds this predicate alone would reasonably guess the other
    way round.
    """
    base = annotation_base_name(annotation)
    return base is not None and base in BLOB_TYPE_NAMES


def function_return_types(functions) -> dict:
    """`{name: declared return annotation}` for a unit's functions.

    Read once and passed down rather than reached for, because
    `struct_construction_plan` is called from three places (the build pass and
    the two backends) and each of them has a different shape of function list.
    One reader means all three see the same evidence.
    """
    out = {}
    for fn in functions or ():
        name = getattr(fn, "name", None)
        if name:
            out[name] = getattr(fn, "return_type", None)
    return out


def _frame_source_structs(arg, candidates: dict):
    """The candidate structs for `arg` if it is a recognised FRAME, else None.

    Two answers and the difference between them is the copy construction's
    whole dependency on the holder analysis:

      * `[S]` — a frame of exactly one struct, and a copy into `S` is a
        slot-for-slot copy of one layout into itself;
      * `[A]`/`[A, B]`/`[A, B, C]` — a frame, but not of a single struct, so
        there is no one layout to copy;
      * `None` — NOT a frame at all.  A name bound from a constructor this path
        does not frame is in `candidates` with an EMPTY list, and that is a
        plain word; a name not in `candidates` at all is a plain word too, and
        the caller refuses it rather than treating it as one, because for a
        COPY the difference between "a plain word" and "a frame whose kind
        this analysis missed" is the difference between refusing a feature and
        copying eight bytes of unrelated memory.
    """
    if not isinstance(arg, F.IdentExpr) or arg.name not in candidates:
        return None
    return list(candidates[arg.name]) or None


# ── THE BLOB-IN-A-FIELD PREMISE ──────────────────────────────────────────
#
# C5's open item, and the one the value-method work meets head-on, so it is
# written down here as a premise with a CHECK rather than left as an accident
# of two unrelated decisions.  A blob (a list or a dict) is not heap storage on
# this path: it is a bump-allocated region of the FUNCTION'S OWN reserved
# scratch, and it dies when that function returns.  So a blob reachable from a
# frame slot has a lifetime that is the shorter of the two — and the moment a
# slot can hold a blob another function built, `self.items.append(x)` inside a
# method appends into reclaimed stack.  The program builds, runs, and returns a
# number nobody wrote.
#
# It is safe TODAY for two reasons, and NEITHER is a property of the frame
# layout.  Both are decisions made elsewhere, and an invariant that holds only
# because of a decision three files away is not an invariant:
#
#   (B1) no method body that actually EXECUTES writes a container into a slot.
#        A literal is materializable at the constructor; a container is a blob
#        with the creating function's lifetime and is not.  The other half of
#        (B1) — a non-literal class-level DEFAULT — is already refused, by
#        `struct_frame_representable`, and is deliberately NOT re-decided
#        below; see `frame_field_premise`.
#   (B2) `S()` does not run `__init__`.  Every slot's value is the class-level
#        DEFAULT, not what the constructor of the language would assign, so the
#        `self.items = List[Self.T]()` in every container-shaped `__init__` in
#        the corpus never executes.
#
# The two have quite different standing and the check below says so:
#
#   * (B1) is a REAL constraint, enforced here.  A method other than `__init__`
#     runs, so `self.items = List[Self.T]()` inside it puts a blob in a slot
#     today, and the refusal is the point.  This is the one the value-method
#     work must keep true.
#   * (B2) is an ENABLING PREMISE, asserted by the emitter (`_emit_struct_
#     constructor` emits no call and refuses `S(x)`) and reported by name.  It
#     is not something this check can prove, and a check that appeared to
#     prove it would be the worst kind of check.
#
# Lift (B1)'s method half and a `reset()` in any struct is a use-after-free.
# Lift (B2) and every `__init__` in the corpus becomes one.  Either change turns
# `self.<container>.<op>()` in every method into appending into reclaimed stack,
# and neither change announces itself: the build stays green and the proof side
# sees one word per slot either way.
FRAME_FIELD_BLOB_PREMISE_B1 = \
    "no executed method writes a container into a field"
FRAME_FIELD_BLOB_PREMISE_B2 = "S() does not run __init__"


def _is_container_value(value, containers: set) -> str:
    """A phrase for why `value` is a container, or "" if it is not one.

    A write into a frame slot is a blob write when the value put there is a
    container, and "is a container" is decidable for three shapes and NOT for
    the fourth, so the three are named and the fourth is a stated gap rather
    than a guess in either direction:

      * a list, tuple or dict DISPLAY — unconditionally a container;
      * a call to something this path does not place — conservatively a
        container, because `List[Self.T]()` is a bump-allocated region and a
        call this path cannot see through might be one.  A call to a framed
        struct of this unit is the exception: its result is a placed frame
        address, one word, with a lifetime the frame layout governs;
      * a NAME this method is known to have bound to a container
        (`containers`) — one hop of propagation, which is what catches
        `tmp = [1, 2, 3]; self.items = tmp`;
      * a bare name or an arithmetic expression — **unknown**, and unknown is
        NOT container.  Treating it as one would refuse `self.a = v` in every
        method, which is the shape the whole frame design exists to support,
        and treating it as definitely-not-one would be the guess this premise
        is arranged to avoid.  So it passes, the gap is written down, and what
        closes it is named: the VALUE KIND of a name, which is
        `model.ValueKinds`' question and the value-method table's, not a
        re-derivation to be smuggled in here.
    """
    if isinstance(value, (F.ListExpr, F.TupleExpr, F.DictExpr)):
        return "a container literal"
    if isinstance(value, F.CallExpr):
        callee = value.func.name if isinstance(value.func, F.IdentExpr) else None
        if callee and _callee_is_placed_frame(callee):
            return ""
        return (f"a call to {callee!r}, whose result this path does not place "
                f"— `List[T]()` and every other container constructor on this "
                f"path is a bump-allocated region, and this one may be")
    if isinstance(value, F.IdentExpr) and value.name in containers:
        return f"the name {value.name!r}, which this method binds to a container"
    return ""


def _container_binding_names(node, receivers, out: set) -> None:
    """Names this method body binds to a container, for the one-hop case.

    Deliberately ONE hop and deliberately local: the point is to catch
    `tmp = [...]; self.x = tmp`, not to compute a value kind.  A name bound in
    another function, or a parameter, is the stated gap above.
    """
    if isinstance(node, list):
        for x in node:
            _container_binding_names(x, receivers, out)
        return
    if isinstance(node, F.FunctionDef):
        return
    target = getattr(node, "target", None)
    if isinstance(target, F.IdentExpr) \
            and isinstance(getattr(node, "value", None),
                           (F.ListExpr, F.TupleExpr, F.DictExpr)):
        out.add(target.name)
    for fname in getattr(node, "__dataclass_fields__", {}):
        if fname in ("line", "col"):
            continue
        _container_binding_names(getattr(node, fname, None), receivers, out)


def _container_write(node, receivers, found: list, containers: set) -> None:
    """Collect `(field, why)` for every container written through a receiver.

    The receiver set is `struct_receivers(st)`, so `this.x = [1]` in a class
    whose methods spell the receiver `this` is seen as readily as `self.x`.
    """
    if isinstance(node, list):
        for x in node:
            _container_write(x, receivers, found, containers)
        return
    if isinstance(node, F.FunctionDef):
        return
    if isinstance(node, F.AssignStmt) and isinstance(node.target, F.MemberExpr) \
            and isinstance(node.target.obj, F.IdentExpr) \
            and node.target.obj.name in receivers:
        why = _is_container_value(node.value, containers)
        if why:
            found.append((node.target.member, why))
        return
    for fname in getattr(node, "__dataclass_fields__", {}):
        if fname in ("line", "col"):
            continue
        _container_write(getattr(node, fname, None), receivers, found,
                         containers)


_PLACED_FRAME_CALLEES = None


def _callee_is_placed_frame(callee: str) -> bool:
    """Whether a call to `callee` yields a frame this path PLACED.

    True for a struct of the module being compiled whose receiver is a frame —
    including a typed-nested field's, which `struct_nested_frame_fields` places
    inside its owner's block.  Both are one word with a lifetime the frame layout
    already governs, which is why a slot may hold them and may not hold a blob.

    The table is a MODULE-level cache keyed on nothing but the compiled struct
    names, because there is no unit to thread through and a container-write scan
    runs per struct; it is cleared by the build pass at the point where it
    publishes the set for a module (`publish_placed_frame_structs`), so a
    second module in one process cannot read the first module's answer.
    """
    return bool(_PLACED_FRAME_CALLEES) and callee in _PLACED_FRAME_CALLEES


def publish_placed_frame_structs(names) -> None:
    """Tell the container-write scan which callees this module places.

    The one piece of unit knowledge `frame_field_premise` needs, and it is
    published rather than threaded because the scan is a node walk with no unit
    in hand — the same reason `attach_field_evidence` puts the evidence on the
    struct instead of passing it down.  Called from `_prepare_functions`, which
    is the single point where the compiled struct set is known.
    """
    global _PLACED_FRAME_CALLEES
    _PLACED_FRAME_CALLEES = set(names or ())


def struct_field_container_writes(struct_def) -> list:
    """`[(field, spelling)]` — the fields this struct's methods put blobs into.

    `__init__` is EXCLUDED, and the exclusion is the whole content of premise
    (B2): that method does not run on this path, so a container it assigns never
    reaches a slot.  Including it would report every container-shaped struct in
    the corpus as broken, which is a true statement about a program that never
    executes and a useless thing to refuse.
    """
    receivers = struct_receivers(struct_def)
    found: list = []
    for m in struct_methods(struct_def):
        if m.name == "__init__":
            continue
        containers: set = set()
        _container_binding_names(getattr(m, "body", None), receivers,
                                containers)
        _container_write(getattr(m, "body", None), receivers, found, containers)
    return found


def frame_field_premise(struct_def) -> tuple:
    """`(ok, which, detail)` — is the blob-in-a-field premise true for `st`?

    The METHOD half of (B1) only, and the exclusion is deliberate rather than
    an omission.  The other half — a non-literal class-level default — is
    already refused, by `struct_frame_representable`, with a message that says
    what is actually wrong with it: the constructor has no scope to evaluate a
    default in.  Re-deciding it here and reporting the blob reasoning instead
    would replace an accurate diagnostic about the default with a true but
    secondary statement about a consequence, and it did: the first version of
    this function re-checked the defaults and turned 67 files' findings from
    "cannot bring its field 'X' up at its default" into the blob message, which
    is a regression in what the reader is told for no new refusal.

    So this is the half the frame layer introduces: a container written by a
    method that EXECUTES, which is the case that was previously unguarded and
    the one the value-method work depends on.

    A container written by `__init__` is not a failure and is not in the answer
    at all; `frame_field_premise_note` is what reports it, because it is the
    evidence that the premise is load-bearing rather than vacuous.
    """
    for field, spelling in struct_field_container_writes(struct_def):
        return (False, FRAME_FIELD_BLOB_PREMISE_B1,
                f"a method of {struct_def.name} assigns {spelling} to "
                f"self.{field}, and a method body RUNS: a list or a dict on "
                f"this path is a bump-allocated region of the function's own "
                f"reserved scratch, so the slot would hold a blob that dies "
                f"when that function returns, and a method reaching through "
                f"the slot afterwards appends into reclaimed stack")
    return (True, None, None)


def frame_field_premise_note(struct_def) -> str:
    """What the premise is resting on for THIS struct, for a diagnostic to say.

    Empty when there is nothing to say.  Non-empty exactly when `__init__` would
    have put a container in a slot had it run — which is the shape of nearly
    every container in the corpus, so this is the sentence that stops the
    premise from being an accident: it names the line whose non-execution is
    doing the work.

    The second sentence is the THIRD door, and it is here because the
    construction shapes added one.  A slot can now hold a container without any
    method writing it: `S([1, 2, 3])` puts a literal straight into a field.  That
    is sound and the reason is worth having on the record rather than in a
    comment three files away — a container LITERAL is built by the function
    whose block is being filled, and it is reachable only through that block,
    and the block is confined to that function's activation by
    `_check_frame_escapes`, so the region outlives every read of the slot.  The
    unsafe neighbour is a container that came back from a CALLEE
    (`construction_dead_blob_refusal` refuses exactly that), because that one
    is bump-allocated in the callee's scratch and the callee has returned by
    the time the store happens.  So the three doors are: a method's write
    (refused, premise B1), `__init__`'s write (does not run, premise B2), and
    a construction argument (a literal is confined with the block; a callee's
    container is refused by name).
    """
    receivers = struct_receivers(struct_def)
    found: list = []
    for m in struct_methods(struct_def):
        if m.name == "__init__":
            containers: set = set()
            _container_binding_names(getattr(m, "body", None), receivers,
                                    containers)
            _container_write(getattr(m, "body", None), receivers, found,
                             containers)
    parts = []
    if found:
        field, spelling = found[0]
        parts.append(
            f"{struct_def.name}.__init__ assigns {spelling} to self.{field}, "
            f"which is a blob in the constructor's scratch rather than a word; "
            f"this is safe only because {FRAME_FIELD_BLOB_PREMISE_B2}, so every "
            f"slot in a fresh {struct_def.name} reads as zero where the "
            f"language's constructor would have put that container")
    literal = _construction_literal_into_field(struct_def)
    if literal:
        field, arg = literal
        parts.append(
            f"{struct_def.name} can also be built with a container in "
            f"self.{field} — {_construction_arg_spelling(arg)} at a "
            f"construction site — and that one is safe for a different reason: "
            f"a container LITERAL is built by the function whose block is being "
            f"filled, it is reachable only through that block, and the block "
            f"cannot leave the function that made it, so the region outlives "
            f"every read of the slot. The unsafe neighbour is a container "
            f"returned by a CALLEE, whose region is bump-allocated in the "
            f"callee's scratch and reclaimed before the store — and that is "
            f"refused by name")
    return " ".join(parts)


def _construction_literal_into_field(struct_def):
    """`(field, argument)` when a construction site puts a container LITERAL in
    a field of this struct, or None.

    The evidence half of `frame_field_premise_note`'s second sentence, and it
    has to be a real walk rather than a guess in either direction: the note is
    printed next to a refusal, so a note that fires for a struct nothing builds
    that way would be sending the reader after a construct their file does not
    contain.

    The walk is over the struct's OWN methods and over every `S(...)` call in
    the same function that names it, which is the only place such a call can
    be: a construction is a call in some function's body, and a function that
    is not this struct's method is not part of `struct_methods`.  A call
    anywhere else in the unit is found by the caller that has the unit's
    statement list; what is here is the part the struct alone can answer.
    """
    for m in struct_methods(struct_def):
        for node in iter_nodes(getattr(m, "body", None)):
            if not isinstance(node, F.CallExpr) \
                    or not isinstance(node.func, F.IdentExpr) \
                    or node.func.name != struct_def.name:
                continue
            slots = struct_frame_slots(struct_def)
            for arg, field in zip(node.args or [], slots):
                if isinstance(arg, (F.ListExpr, F.DictExpr, F.TupleExpr)):
                    return (field, arg)
    return None


def frame_field_premise_refusal(struct_def) -> str:
    """The message for a struct whose blob-in-a-field premise does not hold."""
    ok, which, detail = frame_field_premise(struct_def)
    if ok:
        return ""
    note = frame_field_premise_note(struct_def)
    return (
        f"{struct_def.name} breaks the premise that makes a frame field safe "
        f"to reach through ({which}): {detail} — and `self.<field>.append(x)` "
        f"in a method would then append into reclaimed stack, which is a "
        f"number the source never wrote rather than a failure. "
        + (f"({note}) " if note else "")
        + f"bugs/FORMAL_wide_receiver_by_reference.md records the premise and "
        f"which decisions it currently rests on; the value-method work is what "
        f"has to keep it true")


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
    """`{id(call): (struct, offset, nested)}` — this function's receiver BLOCKS.

    A layout decision, so it lives in the shared model and both backends read
    the same answer: a frame is reserved in the function's PROLOGUE, so it has
    to exist before the body runs and cannot be handed out by a bump pointer
    that walks the body the way the list/dict blob cursor does.

    One BLOCK per call SITE, laid out in walk order. Per site rather than per
    call is what makes a constructor inside a loop safe: the loop reuses its
    site's block, exactly as a C local is reused, so a loop cannot grow the
    stack without bound. `offset` is the block's distance below the bottom of
    the function's ordinary frame — below `SP` on both machines, which is the
    placement `ProofLib.Frame.frameWrite_read_above_sp` needs and the reason a
    method's write to its receiver cannot reach the caller's window.

    `nested` is `[(field_name, slot, struct, offset)]`: the frames of this
    struct's typed-nested fields (`struct_nested_frame_fields`), each with its
    OWN absolute offset into the same scratch, immediately above the object's
    own frame.  This is the tuple's third element and it is additive: a struct
    with no typed-nested field has an empty list, so every existing unpack of
    two elements is still a struct with no nested frames — but the emitters
    read three, because the whole point of the declared-type check is that the
    nested frame is PLACED here rather than hoped for at the use site.
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
        block = struct_frame_block_bytes(st, structs_by_name)
        nested, inner = [], offset + struct_frame_bytes(st)
        for fname, slot, child in struct_nested_frame_fields(st, structs_by_name):
            nested.append((fname, slot, child, inner))
            inner += struct_frame_block_bytes(child, structs_by_name)
        out[id(node)] = (st, offset, nested)
        offset += block
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
