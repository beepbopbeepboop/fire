#!/usr/bin/env python3
"""Which BARE calls to a declared template could have their type arguments
inferred, and what each one would take — the measurement
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
§3 asks for and does not have.

    python3 tools/formal_template_call_census.py [--paths DIR …] [--rows 40]

**The question, and why it is a census and not an argument.** The corpus's
largest codegen cause is one sentence — "`X` is called, and it is imported from
`M`, so the call has to bind a symbol `M` exports. That module does not export
it" — 170 files, 14 symbols, 79 call sites, measured over 710 files by
`bugs/FORMAL_sweep_work_map_2026-10-04_b10.md` §3.1. Every one of those calls is
a BARE call to a name the defining module declares a TEMPLATE, and Mojo infers
a template call's type arguments, so the source is correct and this path is
short. The doc's §3 step 1 is "derive its type arguments from the call's
argument types instead of from a bracket", and it says the type argument "is not
IN the call, it is a property of the argument's DECLARED TYPE". So the size of
the feature is decided by one fact per call site: **is that declared type written
down anywhere the call site can read?**

This instrument answers exactly that and nothing else. It parses; it never
builds, links, or runs Lean, and it is architecture-blind because the question
is about source. Seven buckets, which are the answers an implementation of
`formal/monomorph.py::all_instantiation_calls` has to have, in the order they get
harder:

  * `solvable from the annotations at the call site` — every template parameter
    is decided by a parameter of the declaration (or by a default that IS a type
    spelling), every matched argument has an annotation to unify with, and the
    answer is CONCRETE. Unifying two annotation strings is then arithmetic rather
    than inference, and it is the only bucket that needs nothing but a matcher.
    `def widen[T: AnyType](v: T)` called with an `n: Int` is this bucket —
    `T := Int` — and so is `is_negative(rhs)` with a `var rhs: Int` against
    `def is_negative[dtype: DType, //](value: SIMD[dtype, _])`.
  * `the argument's type is written but does not unify` — the declaration names
    the parameter and the argument IS annotated, but its annotation mentions no
    template parameter. `FormatStruct(writer, "…")` is this bucket and the reason
    is measured rather than guessed: the parameter is `ref[Self.o] writer:
    Self.T` bounded `T: Writer`, and the argument is `writer: Some[Writer]`, so
    the unification has to resolve an EXISTENTIAL against a trait bound — bound
    resolution, not string matching. **This is the bucket that decides whether
    the first one is a patch or a project**, and it is the largest in the
    corpus.
  * `the argument's type is not written down` — the argument in a deciding
    position is a call, an operator, a subscript, a field read or a literal, so
    its type has to come from a RETURN type (this path has no return-type
    inference); **or it is annotated with something this path could not mangle**
    (`SIMD[DType.float32, 4]`'s width is a literal and `type_arg_text` refuses a
    literal), which is the same work for whoever takes it. `dealloc(x^)` is the
    first shape: the argument is a `UnaryOp`.
  * `a type argument is not in the arguments at all` — a template parameter that
    appears in no parameter. A phantom, which no amount of argument inspection
    recovers; it needs a DEFAULT.
  * `a type argument is settled by a comptime default` — **added 2026-10-04.** A
    parameter no argument decides whose DEFAULT is a comptime expression or a
    value rather than a type: `is_32bit[target: CompilationTarget =
    CompilationTarget.current()]()`, `masked[T, invariant: Bool = False]`. It was
    reported `solvable` before, because a call with no arguments reaches no test
    at all and a site nothing was inspected of falls out of every one.
  * `the declaration has no type parameter to substitute` — **added 2026-10-04.**
    The export rule's generic set has the name and the declaration has nothing
    to put in a bracket: `def pick[](v: Int)`, and `fcntl[*types: Intable]` read as
    one until the `*` sigil stopped being treated as punctuation.
    `monomorph.instantiate` refuses exactly this, so promising an instantiation
    here is promising one nothing can build.
  * `the declaration could not be read` — the name is a template by the export
    rule's own generic set and the declaration source would not come out, which
    includes a struct with no `__init__` and arguments to bind.
    Reported rather than dropped, because a census that loses rows quietly is the
    failure `tools/formal_sweep_causes.py` documents as "nobody has looked", and
    a total that silently excludes sites is the one number nobody can use.

**`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
§5b is the measurement of what the last two buckets and the KEYWORD reading cost
the first one: 32 sites became 2, and §5's recommendation — "the matcher bucket is
the only piece of the three that is a patch" — is refuted by it.** The five
corrections are `_arguments_by_parameter` (a keyword argument is in `call.kwargs`,
and a reader that walks `call.args` inspects nothing), `_strip_comments` (a `#`
comment inside a header is both a parameter this reader would misread and a
bracket `_balanced` would count), `MARKER_PIECES` (a packed `*name: Bound` is a
parameter), `_is_type_spelling` (a numeric or boolean default is not a type) and
`_concrete_answer` (an answer that is the enclosing template's own `dtype`, or a
`Self.T`, is not a type argument at all).

**Two flags ride on every row.** `B` — some parameter has a trait bound other
than the unconstrained spellings, so a unification alone cannot choose a
candidate. `S` — the declaration writes the parameter as `Self.T` rather than
`T`, which any matcher has to read as the mention it is: `ref[Self.o] writer:
Self.T` is `std/format/_utils.mojo`'s `__init__`, and a matcher looking for the
bare identifier would file a decidable site in the wrong bucket.

**What this cannot do**, and it is the limit every census in `tools/` states. A
module that does not resolve is reported in its own bucket rather than matched
by name, so a row is a claim about a resolved defining module and not about a
name. And a row says a type argument is INFERABLE FROM SOURCE, which is not the
same as saying the emitted code would be right: the call site also has to be
rewritten to the instantiation the answer names, and that is the half this
instrument does not measure at all.
"""
import argparse
import collections
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import checked_run                                           # noqa: E402
import elaborate                                             # noqa: E402
import fire_compiler as F                                    # noqa: E402
from formal.build import parse_module                        # noqa: E402
from formal.imports import (import_bindings,                 # noqa: E402
                            resolve_module_path)
import formal.model as M                                     # noqa: E402
import formal.monomorph as MM                                # noqa: E402

DEFAULT_PATHS = [
    os.path.join(ROOT, "formal", "hostmods"),
    ROOT,
    os.path.join(ROOT, "..", "new-modular", "Mojo", "stdlib", "std"),
]

# Bounds that unification can satisfy WITHOUT choosing between candidates, in
# every spelling this corpus uses. A parameter bounded by one of these takes
# whatever the argument says; anything else is a TRAIT and a site carrying one is
# flagged `B`, because that is the case where the answer is not a string
# comparison — `T: Writer` against a `Some[Writer]` argument has to pick a
# concrete type for an existential.
#
# **This table is the instrument's judgement, and it is printed rather than
# hidden**: the `B` flag says which rows it decided, so a reader who thinks a
# bound belongs in the table (or out of it) can see every row that turns on it.
# `DType` is in it because a `SIMD[dtype, _]` annotation names a DType VALUE, so
# the unification has nothing to choose.
UNCONSTRAINED_BOUNDS = {
    "", "anytype", "anything", "any", "dtype", "int", "int8", "int16", "int32",
    "int64", "uint8", "uint16", "uint32", "uint64", "bool", "string",
    "staticstring", "stringliteral", "pointer", "simd",
}

_IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")

BUCKET_SOLVABLE = "solvable from the annotations at the call site"
BUCKET_NO_UNIFY = "the argument's type is written but does not unify"
BUCKET_UNDECLARED = "the argument's type is not written down"
BUCKET_PHANTOM = "a type argument is not in the arguments at all"
BUCKET_COMPTIME_DEFAULT = "a type argument is settled by a comptime default"
BUCKET_NO_PARAMETER = "the declaration has no type parameter to substitute"
BUCKET_UNREAD = "the declaration could not be read"

# In the order a reader wants them, which is the order they get harder.
#
# **Seven, and the last two are the ones this instrument was missing** — see
# `classify`'s own docstring and
# `bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
# §5b, which is the measurement of what adding them did to the totals. Both exist
# because a site that CANNOT be answered by argument inspection used to be
# reported as `solvable`, and that is the one direction a census may not round:
# its own header says "a census that rounds an unrecognised shape into `solvable`
# is the one mistake that would make the total an overstatement, and an
# overstatement here is a licence to build the wrong thing".
BUCKETS = [BUCKET_SOLVABLE, BUCKET_NO_UNIFY, BUCKET_UNDECLARED,
           BUCKET_PHANTOM, BUCKET_COMPTIME_DEFAULT, BUCKET_NO_PARAMETER,
           BUCKET_UNREAD]

#: Whether a piece of a parameter or header list binds a parameter at all. `*` is
#: Mojo's keyword-only marker and `**` a spread; `*name: Bound` is a PACKED
#: parameter and `*args: *T` a variadic one, and neither is a marker. The old
#: test was "starts with `*`", which swallowed the packed spelling — and a header
#: whose only parameter is packed then reads as a declaration with NO type
#: parameter, which is what put `std/sys/_libc.mojo`'s `fcntl[*types: Intable]`
#: in the `solvable` bucket with nothing to solve. What to DO with a packed
#: parameter is the variadic ABI's question
#: (`bugs/FORMAL_a_variadic_parameter_read_has_no_abi.md`) and not this
#: instrument's; keeping the parameter in the list is what routes the site to a
#: bucket that says the answer is not in the arguments.
MARKER_PIECES = ("", "/", "*", "**", "//")

#: The two literals this corpus spells the way an identifier is spelled. Named
#: rather than pattern-matched because the reader works on TEXT and `type_arg_text`
#: works on a parsed node, where `False` is a `BoolLiteral` and returns "".
LITERAL_SPELLINGS = ("True", "False")


def _strip_comments(text: str) -> str:
    """`text` with every `# …` comment removed, newlines kept.

    **Before** any bracket walk, and that ordering is the whole point: a comment
    inside a signature is not only a parameter this reader would misread, it is
    also a bracket the walk would count. `std/ffi/__init__.mojo`'s `dlsym` has
    `# Default `dlsym` result is an OpaquePointer.` on the line above
    `result_type: OpaquePointer` INSIDE the header's brackets, and the census
    reported its type parameters as `# Default `dlsym` result is an
    OpaquePointer.\n    result_type` — a comment read as a parameter, from a
    declaration that is a template for one ordinary type argument.

    Newlines are preserved rather than replaced by a space because these
    readers report positions by line (`FunctionDef.line` is 0 and
    `_def_line`'s docstring explains what a reader does with that), and a comment
    removed mid-line must not shift the lines below it. The trailing space keeps
    two tokens from joining into one name.
    """
    out = []
    for line in text.split("\n"):
        at = line.find("#")
        out.append(line if at < 0 else line[:at])
    return "\n".join(out)


def _is_type_spelling(text) -> bool:
    """Whether `text` is a TYPE name this path could substitute.

    The three shapes `formal/monomorph.py::type_arg_text` accepts and nothing
    else: an identifier, a dotted name, a bracketed application of those. **A
    call is not one**, and that is the whole test: `is_32bit[target:
    CompilationTarget = CompilationTarget.current()]()` settles its one type
    parameter with a COMPTIME EXPRESSION, and `masked[T, invariant: Bool = False]`
    settles one with a VALUE — neither is a type argument this path can spell,
    and `type_arg_text` refuses both, so a demand built from either would be a
    mangled name no instantiation was ever built under.

    **Two literal spellings are excluded by name**, because they are the only
    VALUES this corpus writes the way an identifier is written and the reader
    works on TEXT: `invariant: Bool = False` is a comptime parameter holding
    `False`, and `False` as a type argument is not a type. A default whose
    brackets carry an `=` (`origin: Origin[mut=mut]`, a type application with a
    defaulted argument) is not a spelling either, for the same reason
    `type_arg_text` needs a parsed node to read one and this reader has only the
    declaration's text.
    """
    if not isinstance(text, str):
        return False
    text = text.strip()
    if not text or text in LITERAL_SPELLINGS:
        return False
    text = text.strip()
    if not text:
        return False
    i, n = 0, len(text)
    def name():
        # A letter or an underscore FIRST, then letters and digits — which is
        # `_IDENT`'s rule and the reason a numeric default (`rounds: Int = 10`,
        # `std/random/philox.mojo`'s `Random`) is not a spelling. A reader that
        # accepted a leading digit called `10` a type and put the site in
        # `solvable`, which is the rounding this bucket exists to refuse.
        nonlocal i
        if i >= n or not (text[i].isalpha() or text[i] == "_"):
            return ""
        start = i
        while i < n and (text[i].isalnum() or text[i] in "_."):
            i += 1
        return text[start:i]
    while i < n:
        if not name():
            return False
        if i < n:
            if text[i] != "[":
                return False
            i += 1
            while i < n and text[i] != "]":
                if text[i] == ",":
                    i += 1
                    continue
                if not name():
                    return False
                if i < n and text[i] == "[":
                    i += 1
            if i >= n:
                return False
            i += 1                      # the `]`
    return True


def _parameter_name(piece: str) -> str:
    """The NAME a parameter piece binds, or "".

    The head before the first `:` at depth zero, and its LAST identifier — which
    is what a convention prefix leaves behind: `ref[Self.o] writer: Self.T`
    binds `writer` and `var _alloc: ThinAllocation[Self.T]` binds `_alloc`. It is
    needed because a KEYWORD argument names its parameter rather than sitting at
    its index, and `classify` matches keywords by name: `ThinAllocation(
    unsafe_owned_ptr=self._data)` is the corpus's largest instance of the shape
    (17 of the 32 sites this instrument called `solvable`, all of them invisible
    to a reader that only walked `call.args`).
    """
    depth = 0
    for i, ch in enumerate(piece):
        if ch in "[(<":
            depth += 1
        elif ch in "])>":
            depth -= 1
        elif ch == ":" and depth == 0:
            head = piece[:i]
            break
    else:
        head = piece
    idents = _IDENT.findall(head)
    return idents[-1] if idents else ""


# ── the declaration, read off its own source ────────────────────────────────
#
# `fire_compiler` keeps a function's template parameter NAMES
# (`FunctionDef.comptime_params`) and a struct's (the leading `VarDecl` fields,
# whose annotation is the bound), but neither keeps the header's spelling — and
# the spelling is where the CONVENTION and the ORIGIN live. So the declaration
# is read from its own text, through `elaborate`'s extractors, which exist for
# exactly this.

def _balanced(text: str, start: int) -> tuple:
    """`(inside, index after the close)` for the group opening at `start`.

    Over the whole SOURCE and not one line, because a signature in this corpus is
    routinely wrapped: `struct Pointer[\\n    mut: Bool,\\n    //,\\n    T:
    AnyType,\\n](` and `std/memory/alloc.mojo`'s three-line `def __init__(`. A
    line-at-a-time reader sees an unclosed bracket, reports a declaration with NO
    parameters, and files every one of its sites as a phantom — which is how
    this census's largest bucket became an artefact of the stdlib's line length
    before the reader was written.
    """
    open_ch = text[start]
    close_ch = {"[": "]", "(": ")", "<": ">"}.get(open_ch)
    if close_ch is None:
        return "", start
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    return "", start


def _declaration_site(src: str, name: str, member: str = None) -> tuple:
    """`(header, parameter list)` for a declaration, or `("", "")`.

    `member` selects a method (`__init__`) inside a struct or trait source; a
    function passes None and is found by its own name.
    """
    pattern = (rf"^\s*(?:def|fn)\s+{re.escape(member or name)}\s*(\()"
               if member else
               rf"^\s*(?:def|fn|struct)\s+{re.escape(name)}\s*(\[|\()")
    m = re.search(pattern, src, re.M)
    if not m:
        return "", ""
    at = m.start(1)
    if src[at] != "[":
        return "", _balanced(src, at)[0]
    header, after = _balanced(src, at)
    open_paren = src.find("(", after)
    if open_paren < 0:
        return header, ""
    return header, _balanced(src, open_paren)[0]


def bracket_after(src: str, name: str) -> str:
    """The `[...]` a declaration's name is followed by, or ""."""
    return _declaration_site(src, name)[0]


def split_top_level(text: str) -> list:
    """`a, b[c, d], e` → `['a', 'b[c, d]', 'e']`, brackets respected."""
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "[(<":
            depth += 1
        elif ch in "])>":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def is_marker(piece: str) -> bool:
    """Whether a piece of a parameter or header list is a MARKER, not a name.

    `/` is Mojo's positional-only marker and `*` its keyword-only one, and a
    struct header in this corpus also carries `//` — a line comment — inside its
    brackets (`struct Pointer[mut: Bool, //, T: AnyType, …]`). Read as a
    parameter, a marker is mentioned by no annotation, so every declaration
    carrying one lands in the phantom bucket: `def dealloc[T: AnyType, /](…)` is
    `std/memory/alloc.mojo`'s, and its four sites were the first rows this
    instrument misfiled.

    **`*name: Bound` is NOT a marker**, and that is the correction
    `MARKER_PIECES` records: the old test was "starts with `*`", so a PACKED
    parameter — `fcntl[*types: Intable](fd, cmd, *args: *types)` — was dropped
    from the header as if it were punctuation, and a declaration whose only type
    parameter is packed then reads as one with nothing to substitute. The
    variadic-ABI refusal is the honest answer for those sites and this
    instrument is not the thing that decides it; what it must not do is call them
    `solvable`.
    """
    return (piece or "").strip() in MARKER_PIECES


def split_default(piece: str) -> tuple:
    """`(head, default_or_None)` — the first `=` at bracket depth ZERO.

    Depth matters because an `=` inside a type argument is not a default:
    `struct Pointer[mut: Bool, T: AnyType, origin: Origin[mut=mut], *,
    address_space: AddressSpace = .GENERIC]` has one default, and splitting at
    the first `=` blindly turned `origin: Origin[mut=mut]` into a parameter
    `origin` bound `Origin[mut` with the default `mut]`.
    """
    depth = 0
    for i, ch in enumerate(piece):
        if ch in "[(<":
            depth += 1
        elif ch in "])>":
            depth -= 1
        elif ch == "=" and depth == 0:
            return piece[:i], piece[i + 1:].strip() or None
    return piece, None


def template_parameters(decl_src: str, name: str) -> list:
    """`[(parameter, bound, default_or_None)]` from a declaration's header."""
    out = []
    for piece in split_top_level(bracket_after(decl_src, name)):
        piece, default = split_default(piece)
        bound = ""
        if ":" in piece:
            piece, bound = piece.split(":", 1)
        param = piece.strip()
        if not is_marker(param):
            out.append((param, bound.strip(), default))
    return out


def init_parameter_lists(decl_src: str) -> list:
    """Every `__init__`'s parameter pieces, in source order."""
    out = []
    for m in re.finditer(r"^\s*def\s+__init__\s*\(", decl_src, re.M):
        out.append(split_top_level(_balanced(decl_src, m.end() - 1)[0]))
    return out


def without_receiver(pieces) -> list:
    """The parameters an argument list binds — a constructor's receiver is not
    one of them, and `ref[Self.o] writer` is not a receiver however it reads."""
    out = [p for p in pieces if not is_marker(p)]
    if out and re.match(r"^(out|inout|mut|ref)\b", out[0].strip()):
        out = out[1:]
    return out


def by_arity(lists, argc: int, names=()):
    """The `__init__` overload whose parameter count is nearest `argc`, among
    those that MENTION a template parameter.

    NEAREST rather than exact, because a defaulted parameter is spelled in the
    source and absent from the call (`__init__(out self, a: Int, b: Int = 0)`
    has to be selectable by a one-argument call). A call no overload takes is
    refused by the build, and re-deriving that here would be a second opinion
    about a question this census does not own.

    The MENTION preference is a real ambiguity rather than a nicety:
    `std/memory/pointer.mojo`'s `Pointer` declares two one-argument `__init__`
    overloads — the user's and an internal `__init__(out self, _mlir_value:
    Self._mlir_type)` — and picking the first of them classifies every
    `Pointer(…)` site as a phantom when what the source means is the overload
    that says `T`. An overload that mentions no template parameter carries no
    inference at all, so preferring the ones that do is the honest tie-break,
    and it is reported rather than hidden: the row prints the parameter list it
    unified against.
    """
    best, best_key = None, None
    for pieces in lists:
        params = without_receiver(pieces)
        named = sum(1 for p in params if any(mentions(p, n) for n in names))
        key = (-named, abs(len(params) - argc))
        if best_key is None or key < best_key:
            best, best_key = params, key
    return best


def parameter_pieces(decl_src: str, name: str, argc: int):
    """`[(piece, mention text)]` for the signature an `argc`-argument call hits.

    The MENTION TEXT is the parameter's whole declaration piece: its convention
    AND its annotation. That is not a detail — `fire_compiler` normalises
    `ref[Self.o] writer: Self.T` to the annotation `Self.T` and the conv `ref`,
    so the only place `Self.o` still exists is the declaration source, and `o` is
    a type argument the arguments DO carry. `__init__(out self, ref[Self.o]
    writer: Self.T, name: StaticString)` therefore decides both `T` and `o` from
    its parameters, and a census reading only the annotation calls `o` a phantom
    — a false negative that would move the corpus's largest measured shape
    (`FormatStruct`, 111 of its 170 files) into the wrong bucket.

    A STRUCT template is CONSTRUCTED, so its signature is one of its `__init__`
    overloads and the argument count selects which;
    `elaborate.extract_fn_source` documents the same selection for same-named
    function overloads, and `model.init_body_stores` is what inlines the body at
    the construction site.

    None for a struct with no `__init__` and a non-zero argument count: there is
    nothing to unify against, and the honest answer is that the signature could
    not be read.
    """
    if re.search(rf"^\s*(?:def|fn)\s+{re.escape(name)}\s*\[", decl_src, re.M):
        _header, params = _declaration_site(decl_src, name)
        return [(p, p) for p in split_top_level(params) if not is_marker(p)]
    lists = init_parameter_lists(decl_src)
    if not lists:
        return [] if argc == 0 else None
    names = [p for p, _b, _d in template_parameters(decl_src, name)]
    return [(p, p) for p in by_arity(lists, argc, names)]


def mentions(annotation, param: str) -> bool:
    """Whether `annotation` names the template parameter `param`.

    `Self.T` counts, and whole identifiers only: `StaticString` is not a mention
    of `T`, and `ref[Self.o] writer: Self.T` is a mention of BOTH `T` and `o`.
    """
    if not isinstance(annotation, str) or not annotation or not param:
        return False
    idents = _IDENT.findall(annotation)
    for i, ident in enumerate(idents):
        if ident == param:
            return True
        if ident == "Self" and i + 1 < len(idents) and idents[i + 1] == param:
            return True
    return False


def is_unconstrained(bound) -> bool:
    if not isinstance(bound, str) or not bound.strip():
        return True
    head = bound.strip().split(":")[0].split("[")[0].strip().lower()
    return head in UNCONSTRAINED_BOUNDS


# ── the call site ───────────────────────────────────────────────────────────

def declared_types(fn) -> dict:
    """`{name: annotation}` for what this function's own text declares.

    Its PARAMETERS and its annotated locals, because those are the two places a
    call site can read an argument's type from. `FunctionDef.params` is
    `[(name, annotation)]` in this tree; reading it as anything else leaves
    `declared` empty, and then every argument looks undeclared — which is a
    census reporting the whole corpus as needing return-type inference, from a
    destructuring mistake.
    """
    out = {}
    for entry in (getattr(fn, "params", None) or []):
        if isinstance(entry, (list, tuple)) and entry:
            out[entry[0]] = entry[1] if len(entry) > 1 else None
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        name = getattr(node, "name", None)
        if isinstance(node, F.VarDecl) and name and \
                getattr(node, "type_ann", None):
            out.setdefault(name, node.type_ann)
    return out


def argument_source(arg, declared: dict) -> tuple:
    """`(kind, text)` — where an argument's declared type would come from.

    A kind this instrument does not know is reported as `unknown` rather than
    folded into a neighbouring one: a census that rounds an unrecognised shape
    into "solvable" is the one mistake that would make the total an
    overstatement, and an overstatement here is a licence to build the wrong
    thing.
    """
    if isinstance(arg, F.IdentExpr):
        ann = declared.get(arg.name)
        if isinstance(ann, str) and ann.strip():
            return "annotation", ann
        return "a name with no annotation", ""
    if isinstance(arg, F.CallExpr):
        return "a call result", ""
    if isinstance(arg, (F.UnaryOp, F.BinaryOp)):
        return "an operator", ""
    if isinstance(arg, F.MemberExpr):
        return "a field read", ""
    if isinstance(arg, F.SubscriptExpr):
        return "a subscript", ""
    if isinstance(arg, (F.TernaryExpr, F.ListExpr, F.TupleExpr, F.DictExpr,
                        F.SetExpr)):
        return "a compound expression", ""
    if type(arg).__name__.endswith("Literal"):
        return "a literal", ""
    return "unknown", ""


def _arguments_by_parameter(params, call):
    """`[(parameter index, argument node or None)]` — a KEYWORD's position is its
    name, and a POSITIONAL's is its index.

    The pairing is what `classify` walks instead of `enumerate(call.args)`, and
    the two are not the same thing: `ThinAllocation(unsafe_owned_ptr=self._data)`
    passes one argument and it is in `call.kwargs`, so an index walk over
    `call.args` sees NOTHING and the site falls out of every test into
    `solvable`. That is not a corner — it is 20 of the 32 sites the pre-2026-10-04
    version of this instrument reported as `solvable`, and the corpus's largest
    measured shape among them (`bugs/
    FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md` §5b).

    A keyword wins over the positional at the same index, because a call cannot
    pass both (`f(x, x=1)` is CPython's `TypeError`, and a call that does is
    refused by `model.struct_construction_plan` / `bind_call_arguments` long
    before this reads it). A parameter with no argument at all gets None, which is
    the DEFAULT's case rather than a missing one.
    """
    args = list(call.args or ())
    kwargs = {k: v for k, v in (getattr(call, "kwargs", None) or ())}
    out = []
    for i, (piece, _text) in enumerate(params):
        name = _parameter_name(piece)
        if name and name in kwargs:
            out.append((i, kwargs[name]))
            continue
        out.append((i, args[i] if i < len(args) else None))
    return out


def classify(call, declared: dict, decl, enclosing=()):
    """`(bucket, bounded, self_qualified)` for one bare call to a template.

    `decl` is `(template parameters, [(piece, mention text)])` or None, which is
    its own bucket rather than a skip, and `enclosing` is the type parameters of
    the definition the call is written in (`_own_tparams`) — see
    `_concrete_answer` for the two measured sites that need them.

    **The order of the questions is the order the facts are decided in**, and the
    last two are questions the pre-2026-10-04 version did not ask at all — which
    is why it reported 32 `solvable` sites where 4 are (`…_inferrable.md` §5b):

    1. is there a declaration to read, and does it have anything to substitute?
       (`fcntl[*types: Intable]` is a template by the export rule and has no type
       parameter this reader can see, and `monomorph.instantiate` refuses it with
       exactly that sentence);
    2. is every parameter mentioned somewhere, or settled by a default? (unchanged,
       and the phantom bucket);
    3. **for a parameter no ARGUMENT decides, is its DEFAULT a type this path
       could substitute?** `is_32bit[target: CompilationTarget =
       CompilationTarget.current()]()` and `masked[T, invariant: Bool = False]`
       both settle their last parameter with a comptime EXPRESSION or a VALUE, and
       `type_arg_text` refuses both — so the site is not `solvable`, and a census
       that says it is has produced a licence to build the wrong thing;
    4. for each parameter an argument DOES decide, can that argument's declared
       type be read, and does a trait-bounded one unify? (the two buckets the
       doc's §5 buckets 1 and 2 are about).
    """
    if decl is None:
        return BUCKET_UNREAD, False, False
    tparams, params = decl
    bounded = any(not is_unconstrained(b) for _p, b, _d in tparams)
    selfq = any("Self" in (text or "") and mentions(text, p)
                for p, _b, _d in tparams for _n, text in params)
    names = [p for p, _b, _d in tparams]
    if not names:
        return BUCKET_NO_PARAMETER, bounded, selfq
    # A parameter no argument can carry. Asked over the WHOLE signature rather
    # than the matched positions, because a parameter nothing mentions is
    # invisible to any argument — and a parameter with a DEFAULT is not that,
    # because Mojo fills it in without being told: `invariant: Bool = False` in
    # `std/sys/intrinsics.mojo`'s `strided_load` and `address_space: AddressSpace
    # = .GENERIC` in `std/memory/pointer.mojo`'s `Pointer` are both omitted at
    # every call site and both carried. Counting them as phantoms put the two
    # measured intrinsics in the wrong bucket, so a DEFAULT settles a parameter
    # and only a parameter with neither a mention nor a default is a phantom.
    undecided = [p for p, _b, _d in tparams
                 if not any(mentions(text, p) for _n, text in params)
                 and not _d]
    if undecided:
        return BUCKET_PHANTOM, bounded, selfq
    bound_of = {p: is_unconstrained(b) for p, b, _d in tparams}
    paired = _arguments_by_parameter(params, call)
    decided_by_an_argument = set()
    for i, arg in paired:
        deciding = [p for p in names if mentions(params[i][1], p)]
        if not deciding:
            continue                  # this argument decides no type
        if arg is None:
            continue                  # …and no argument reached this one at all,
            #                     which is the DEFAULT's case, asked below
        decided_by_an_argument.update(deciding)
        kind, text = argument_source(arg, declared)
        if kind != "annotation":
            return BUCKET_UNDECLARED, bounded, selfq
        # A TRAIT-BOUNDED parameter is the one case where an annotation that
        # does not already name the parameter is not the answer: `T: Writer`
        # against a `writer: Some[Writer]` has to pick a concrete type for an
        # existential, which is bound resolution rather than a string match. An
        # UNBOUNDED one takes whatever it is given — `def widen[T: AnyType](v:
        # T)` called with an `n: Int` unifies to `T := Int`, which is why the
        # check is asked of the bounded parameters only and not of every one.
        bounded_deciding = [p for p in deciding if not bound_of[p]]
        if bounded_deciding \
                and not any(mentions(text, p) for p in bounded_deciding):
            return BUCKET_NO_UNIFY, bounded, selfq
        # …and the answer has to be a TYPE ARGUMENT, not the enclosing
        # template's own parameter reached through the annotation. Asked after
        # the bound check, so a trait-bound that does not unify is still reported
        # as the bound-resolution question it is.
        if not _concrete_answer(text, deciding, enclosing):
            return BUCKET_UNDECLARED, bounded, selfq
    # A DEFAULT the path cannot spell, and it is asked only of the parameters no
    # argument decided: a default that IS a type spelling is the answer
    # (`origin: Origin[mut=mut]`), and one that is not cannot be mangled into a
    # demand at all. Which is the difference between `solvable` and this row, and
    # it is the difference between a feature that answers a site and one that
    # builds a mangled name nothing was ever compiled under.
    for p, _b, default in tparams:
        if default and p not in decided_by_an_argument \
                and not _is_type_spelling(default):
            return BUCKET_COMPTIME_DEFAULT, bounded, selfq
    return BUCKET_SOLVABLE, bounded, selfq


def bare_callee(call):
    """`(name, argc)` for a BARE callee, or None.

    A bare name only. A dotted callee (`mod.f(…)`) is a name this file did not
    bind, a subscripted one (`f[T](…)`) already carries its type arguments in
    the source, and a member one (`self.f(…)`) is a method whose receiver this
    instrument does not resolve.
    """
    func = getattr(call, "func", None)
    if not isinstance(func, F.IdentExpr):
        return None
    return func.name, len(call.args or []) + len(call.kwargs or [])


# ── scopes ──────────────────────────────────────────────────────────────────

def is_definition(st) -> bool:
    """Whether `st` opens a new SCOPE rather than being written in this one."""
    return isinstance(st, F.FunctionDef) or type(st).__name__ in (
        "StructDef", "TraitDef", "ClassDef")


def _own_tparams(defn) -> frozenset:
    """The type parameters of the FUNCTION TEMPLATE this definition is.

    `fire_compiler`'s own answer (`FunctionDef.comptime_params`), and it is asked
    for one reason: a call inside a template's body can unify an argument's
    annotation against a callee's parameter and get the ENCLOSING template's
    parameter back — `is_negative(val)` inside `def bit_width[dtype: DType,
    width: Int](val: SIMD[dtype, width])` answers `dtype := dtype` — which is not
    a type argument any instantiation can be mangled under. A method's enclosing
    parameters belong to its STRUCT and arrive as `Self.X`, which
    `_concrete_answer` refuses without knowing them.
    """
    return frozenset(getattr(defn, "comptime_params", None) or ())


def _concrete_answer(text: str, deciding, enclosing) -> bool:
    """Whether unifying `text` against `deciding` yields TYPE ARGUMENTS.

    Three ways it does not, and all three are measured sites rather than theories
    — `std/bit/bit.mojo`'s `is_negative(val)` (the answer is the enclosing
    template's own `dtype`), `std/memory/owned_pointer.mojo`'s
    `ThinAllocation(unsafe_owned_ptr=unsafe_from_raw_pointer)` whose parameter is
    annotated `Pointer[Self.T, MutUntrackedOrigin]` (the answer is `Self.T`), and
    `std/memory/alloc.mojo`'s `dealloc`, whose whole row is the shape.

    1. **A `Self.`-qualified mention.** `Self.T` names the enclosing TYPE's
       parameter, and no mangler can spell it.
    2. **A bare mention of one of the ENCLOSING definition's own type
       parameters** (`_own_tparams`), which is (1) without the qualification.
    3. **A deciding parameter the annotation does not mention at all**: the answer
       is then the whole annotation, so the annotation has to BE a type name —
       `widen(v: T)` against `n: Int` gives `T := Int`, which is the row this
       bucket exists for, while `Pointer[Self.T, …]` against an `Int` argument
       gives a shape mismatch no matcher can paper over.
    """
    idents = _IDENT.findall(text or "")
    for i, ident in enumerate(idents):
        if ident == "Self" and i + 1 < len(idents):
            return False
    if not enclosing:
        pass
    for p in deciding:
        if mentions(text, p) and p in enclosing:
            return False
    if any(not mentions(text, p) for p in deciding):
        return _is_type_spelling(text)
    return True


def _statements_of(st) -> list:
    """Whatever statement lists a struct or trait body carries besides methods."""
    out = []
    for field in (getattr(st, "__dataclass_fields__", {}) or {}):
        if field in ("body", "statements"):
            out += list(getattr(st, field) or [])
    return out


def nested_scopes(stmts, path: str) -> list:
    """The scopes of the DEFINITIONS inside `stmts`, and nothing else.

    Separate from `scopes` because of one duplication this instrument had when
    it was one function: a method's own statements were emitted once by the
    struct branch that found the method and again by the recursion over that
    method's body, so every call in a struct method was counted twice —
    `std/memory/alloc.mojo`'s three `FormatStruct` sites printed as six. A
    census whose totals are a function of its own traversal is not a
    measurement, so the recursion here descends into definitions ONLY.
    """
    out = []
    for st in stmts or []:
        if isinstance(st, F.FunctionDef):
            out.append((declared_types(st), _plain_nodes(st), _own_tparams(st)))
            out.extend(nested_scopes(st.body or [], path + "/" + st.name))
        elif is_definition(st):
            for m in (getattr(st, "methods", None) or []):
                # A METHOD's enclosing type parameters are the STRUCT's, and the
                # corpus reaches them as `Self.X` in the annotations rather than
                # as a bare name — which `_concrete_answer` refuses whatever the
                # struct declared, so nothing is lost by not reading the struct's
                # header here.
                out.append((declared_types(m), _plain_nodes(m), ()))
                out.extend(nested_scopes(
                    m.body or [],
                    f"{path}/{getattr(st, 'name', '?')}.{m.name}"))
            out.extend(nested_scopes(_statements_of(st), path))
    return out


def _plain_nodes(defn) -> list:
    """The nodes of a definition's own statements, excluding nested ones.

    `iter_nodes` descends into a nested `def`, so including it would emit every
    call inside a nested definition twice: once under the outer definition's
    scope and once under its own.
    """
    plain = [x for x in (getattr(defn, "body", None) or [])
             if not is_definition(x)]
    return list(M.iter_nodes(plain))


def scopes(stmts, scope=None) -> list:
    """`[(scope, [node, …])]` — every node, with the scope it is written in.

    Per SCOPE and not per top-level statement, because "is this name a
    parameter" is a question about the scope and `iter_nodes` has no parent: a
    struct's METHOD has its own parameters, and reading them as the struct's — or
    as the module's — is what made the corpus's largest measured shape
    (`FormatStruct`, called from `Allocation.write_to(self, mut writer:
    Some[Writer])`) come out as "the argument's type is not written down" when
    the annotation is written three lines above the call.
    """
    out = []
    for st in stmts or []:
        if isinstance(st, F.FunctionDef):
            out.append((declared_types(st), _plain_nodes(st), _own_tparams(st)))
        elif is_definition(st):
            for m in (getattr(st, "methods", None) or []):
                out.append((declared_types(m), _plain_nodes(m), ()))
            for s in _statements_of(st):
                out.extend(scopes([s], scope))
        else:
            out.append((scope or {}, list(M.iter_nodes([st])), ()))
        if is_definition(st):
            out.extend(nested_scopes(
                st.body if isinstance(st, F.FunctionDef)
                else _statements_of(st),
                getattr(st, "name", "?") or "?"))
    return out


# ── the corpus ──────────────────────────────────────────────────────────────

def defining_module(importer: str, module: str):
    """`(template names, source)` for the module a name is imported from, or
    None.

    `resolve_module_path` is the BUILD's own resolver, asked the way the build
    asks it (`relative_to` the importing file), because a census that resolved
    module names by a rule of its own would be measuring a different corpus than
    the refusal it is about — and `template_names` is
    `reflect.export_exclusions`'s generic set, so "is a template" is the export
    rule's own answer rather than a second one.
    """
    path = resolve_module_path(module, relative_to=importer,
                              project_root=importer)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return None
    return set(MM.template_names(src)), src


def declaration_for(src: str, name: str, argc: int):
    """`(template parameters, [(piece, mention text)])` for a call, or None.

    **The comments come off the module source first**, and that ordering is the
    fix rather than a tidiness: `std/ffi/__init__.mojo`'s `dlsym` carries
    `# Default `dlsym` result is an OpaquePointer.` on the line above
    `result_type: OpaquePointer` INSIDE the header's brackets, and a comment read
    as a parameter is how that declaration came to report a type parameter called
    `# Default `dlsym` result is an OpaquePointer.`. A comment can also carry a
    bracket, which would corrupt `_balanced`'s depth count rather than merely
    misreading one name — so it is stripped here, once per declaration, where
    every reader below sees comment-free text.
    """
    src = _strip_comments(src)
    kind_is_fn = bool(re.search(rf"^\s*(?:def|fn)\s+{re.escape(name)}\s*\[",
                                src, re.M))
    decl_src = (elaborate.extract_fn_source(src, name, argc) if kind_is_fn
                else elaborate.extract_struct_source(src, name))
    if not decl_src:
        return None
    pieces = parameter_pieces(decl_src, name, argc)
    if pieces is None:
        return None
    return template_parameters(decl_src, name), pieces


def collect(paths):
    """The census. Returns `(rows, n_files, n_calls, unresolved)`.

    A row is `(file, line, callee, defining module, bucket, bounded,
    self_qualified, parameters)`.
    """
    files = []
    for base in paths:
        if os.path.isfile(base):
            files.append(base)
            continue
        for dirpath, dirs, names in os.walk(base):
            if "/build/" in dirpath or dirpath.endswith("/build"):
                continue
            # `.tmp` and `.git` are not CORPUS, they are this worktree's
            # scratch and its history, and a census whose numbers move with
            # whatever a scratch build left behind cannot be quoted in a bug
            # doc — which is the only reason this instrument exists. It is
            # pruned IN PLACE because `DEFAULT_PATHS` includes the repository
            # root, so the walk descends into `.tmp/<some test's tmpdir>/` and
            # counts `.mojo` files a test wrote an hour ago; measured on
            # 2026-10-05, four of this instrument's `unresolved` rows were
            # `.tmp/` scratch and one of them was a call to `FormatStruct` —
            # this doc's own subject, in a file that does not exist.
            #
            # `checked_run.is_derived_dir` is the REPOSITORY'S one answer to
            # "is this directory's content an input", and it is the reader
            # `tools/dangling_doc_refs.py` already reuses rather than keeping a
            # second list of "not part of the repo"; two lists are two answers
            # to one question and they eventually disagree. `formal_returnless_
            # census.py` walks the same corpus and now asks the same reader.
            dirs[:] = [d for d in dirs if not checked_run.is_derived_dir(d)]
            files += [os.path.join(dirpath, n) for n in sorted(names)
                      if n.endswith(".mojo")]
    rows, unresolved = [], []
    cache: dict = {}
    seen = set()
    n_files = n_calls = 0
    for path in sorted(files):
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                stmts = parse_module(f.read(), filename=path)
        except Exception:                                  # noqa: BLE001
            continue
        n_files += 1
        bindings = import_bindings(stmts)
        if not bindings:
            continue
        # `(name, argc) -> [(call, scope)]`, so a call is classified against the
        # ONE overload its own argument count selects. Keyed on the name alone it
        # classified every call once per declared arity of that name, which
        # makes every total here a function of the corpus's overloads rather than
        # of its call sites.
        wanted = collections.defaultdict(list)
        for scope, nodes, enclosing in scopes(stmts):
            for node in nodes:
                if not isinstance(node, F.CallExpr):
                    continue
                got = bare_callee(node)
                if got is not None and got[0] in bindings:
                    wanted[got].append((node, scope, enclosing))
        for (name, argc), sites in sorted(wanted.items()):
            module, defining = bindings[name]
            key = (real, module)
            if key not in cache:
                cache[key] = defining_module(path, module)
            found = cache[key]
            if found is None:
                unresolved.append((os.path.relpath(path, ROOT), module,
                                   defining, len(sites)))
                continue
            templates, src = found
            if defining not in templates:
                continue        # not a template: this census is about the bare
                continue        # call to a DECLARED TEMPLATE, nothing else
            n_calls += len(sites)
            decl = declaration_for(src, defining, argc)
            spelled = ", ".join(f"{p}: {b}" if b else p
                                for p, b, _d in (decl[0] if decl else []))
            for node, scope, enclosing in sites:
                bucket, bounded, selfq = classify(node, scope, decl, enclosing)
                rows.append((os.path.relpath(path, ROOT), node.line, name,
                             module, bucket, bounded, selfq, spelled))
    return rows, n_files, n_calls, unresolved


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--paths", nargs="*", default=None,
                    help="files or directories to walk (default: this "
                         "repository, formal/hostmods and the stdlib)")
    ap.add_argument("--rows", type=int, default=40,
                    help="how many per-callee rows and call-site rows to print")
    args = ap.parse_args(argv)

    rows, n_files, n_calls, unresolved = collect(args.paths or DEFAULT_PATHS)
    kinds = collections.Counter(r[4] for r in rows)
    print(f"files scanned: {n_files}   bare calls to an imported name that is "
          f"a declared template: {n_calls}   call sites classified: {len(rows)}")
    for bucket in BUCKETS:
        print(f"   {kinds.get(bucket, 0):6d}  {bucket}")
    print(f"   of which some parameter is trait-bounded (`B`): "
          f"{sum(1 for r in rows if r[5])}")
    print(f"   of which the declaration writes it as `Self.T` (`S`): "
          f"{sum(1 for r in rows if r[6])}")
    if unresolved:
        print(f"   the defining module did not resolve for "
              f"{len(unresolved)} (file, name) pair(s) — reported, never "
              f"matched by name:")
        for path, module, defining, n in unresolved[:10]:
            print(f"    {path}  {module}.{defining}  x{n}")

    per = collections.Counter()
    for _path, _line, name, module, bucket, _b, _s, _p in rows:
        per[(name, module, bucket)] += 1
    print("\n   callee                                defining module"
          "        bucket                                        sites")
    for (name, module, bucket), n in per.most_common(args.rows):
        print(f"   {name:36s} {module:20s}  {bucket:44s} {n:5d}")

    print("\nrows:")
    for path, line, name, module, bucket, bounded, selfq, params in \
            rows[:args.rows]:
        flags = f"{'B' if bounded else '-'}{'S' if selfq else '-'}"
        print(f"   {path}:{line}  {name}(…)  [{params}]  {bucket}  {flags}")
    return 0


if __name__ == "__main__":
    sys.exit(main())