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

INT_KIND = "int"
STR_KIND = "str"
LIST_PREFIX = "list"


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
            return _unify(self.kind_of(e.body), self.kind_of(e.orelse))
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


def _self_field_names(node, out: set) -> None:
    """Add to `out` every name reached as `self.<name>` anywhere under `node`.

    A field access either way round declares a field: `self.x = 1` writes one,
    and a bare `self.x` reads one that some other method (or the caller) filled
    in. A Python class that only ever READS a field declares it just as really
    as one that assigns it, and a width computed from the assignments alone
    would call such a class a zero-field marker and then compile a read of
    storage that nothing ever wrote.

    A method call is not a field access. `self.helper()` names a method, and
    counting it would add a field to every class that calls one of its own
    methods — enough to make a genuinely one-word class measure wide. So a
    `CallExpr` whose callee is `self.<name>` contributes nothing and its
    callee is not descended into, while its arguments still are (a method can
    be handed `self.x` as an argument, which is a real field access).

    A nested `FunctionDef` is not descended into either: its `self`, if it has
    one, is a different binding from the struct's receiver."""
    if isinstance(node, list):
        for x in node:
            _self_field_names(x, out)
        return
    if isinstance(node, F.FunctionDef):
        return
    if isinstance(node, F.CallExpr) and isinstance(node.func, F.MemberExpr) \
            and isinstance(node.func.obj, F.IdentExpr) \
            and node.func.obj.name == "self":
        for a in node.args or []:
            _self_field_names(a, out)
        for _k, v in (node.kwargs or []):
            _self_field_names(v, out)
        return
    if isinstance(node, F.MemberExpr) and isinstance(node.obj, F.IdentExpr) \
            and node.obj.name == "self":
        out.add(node.member)
        return
    for fname in getattr(node, "__dataclass_fields__", {}):
        if fname in ("line", "col"):
            continue
        _self_field_names(getattr(node, fname, None), out)


def struct_field_names(struct_def) -> list:
    """Every field name this struct has, in a stable order.

    THE field set, and therefore the whole of the representability decision
    (`struct_fits_one_word` reads its length). It is derived from every place a
    field can be introduced rather than from the class body alone, because the
    class body alone is not where most of this repo's own classes put their
    fields:

      * a class-level `VarDecl` / assignment — the annotated or defaulted
        spelling (`x: int`, `x: int = 0`, `x = 0`);
      * a class-level `__slots__ = (...)` — the one class-level assignment
        that names fields instead of storing one, contributing the names it
        lists rather than the name `__slots__`;
      * any `self.<name>` a method of this struct touches — the Python-style
        spelling, in which the fields are whatever `__init__` assigns.

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

    Note what this cannot do: it has no type information, so it cannot tell a
    per-instance field from a class-level CONSTANT (`_SIGNED = 1`), and it
    counts both. That is the conservative direction — a constant counted as a
    field can only cause a refusal, never a wrong answer — but it does mean a
    reported width is an upper bound, which is why every refusal that quotes
    one also quotes the names it counted."""
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
    for method in struct_methods(struct_def):
        touched = set()
        _self_field_names(getattr(method, "body", None), touched)
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
    count is an upper bound (it cannot separate a per-instance field from a
    class-level constant) and a bare number would be asking the reader to trust
    a census they cannot check. The list is bounded by `MAX_LISTED_FIELDS`:
    past that the count itself is the news and the first few names are enough
    to confirm the tool looked at the class you think it did."""
    names = struct_field_names(struct_def)
    if not names:
        return "no fields at all"
    if len(names) <= MAX_LISTED_FIELDS:
        return f"{len(names)} field(s): {', '.join(names)}"
    return (f"{len(names)} fields (too many to list; the first "
            f"{MAX_LISTED_FIELDS} are {', '.join(names[:MAX_LISTED_FIELDS])})")


def struct_width_cost(struct_def) -> str:
    """What closing this particular gap would take, in one clause.

    Said per width rather than as one blanket "widen the model", because the
    three cases are genuinely different problems and a refusal that treats them
    alike hides that:

      * exactly two fields is a one-word model plus a second word — an ABI
        change, and the cheapest of the three to close;
      * a handful is the same ABI change with a layout to invent;
      * dozens is a categorically different thing: a register allocator and a
        calling convention that passes aggregates, not a two-word special case.

    A formal backend's diagnostic is part of its output, so it should say which
    of those the reader is actually facing."""
    n = struct_field_count(struct_def)
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

    Only meaningful for a struct of at most one field; a wider one has no
    representation to bring up in the first place."""
    if struct_field_count(struct_def) != 1:
        return (DEFAULT_NONE, None)
    field_name = struct_sole_field_name(struct_def)
    default = None
    for field in struct_fields(struct_def):
        if struct_field_name(field) == field_name:
            default = getattr(field, "value", None)
            break
    if default is None:
        return (DEFAULT_NONE, None)
    if isinstance(default, F.IntLiteral):
        return (DEFAULT_INT, int(default.value))
    if isinstance(default, F.BoolLiteral):
        return (DEFAULT_INT, 1 if default.value else 0)
    if isinstance(default, F.StringLiteral) \
            and isinstance(default.value, str) and not default.is_bytes:
        return (DEFAULT_STRING, default.value)
    return (DEFAULT_OPAQUE, field_name)


def struct_fits_one_word(struct_def) -> bool:
    """True when the struct's whole state is a single word.

    Zero fields (a marker) and one scalar field are both exactly one word: for
    the single-field case the receiver IS the field, so `self.n` is `self` and
    no indirection is needed anywhere. The count is the DERIVED one, so a class
    that assigns its field in `__init__` gets the same treatment as one that
    declares it — which is what makes `self.n` and `c.n` the same storage
    instead of two unrelated words that happen to share a spelling."""
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
