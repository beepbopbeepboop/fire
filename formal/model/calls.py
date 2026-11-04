from . import *

# ── a function that produces NO value, and what that is worth at a use ──────
#
# A `def` with no `return` returns NOTHING in CPython, and `None` is not a word:
# a value on this path is one 64-bit word (`ValueKinds`' own header says so),
# and a word has no way to say "no value". Both emitters' epilogues leave the
# return register holding whatever the callee's last instruction put there, so a
# call to such a function answers a number nobody wrote — measured on BOTH
# architectures from one source, `print(g(1, 2))` for `def g(a, b): w = 1`
# printed `0` where CPython printed `None`, and `bugs/
# FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.md`
# records that the word is not even stable (it is not the caller's leftover
# either: a call before it that returned 77 did not survive).
#
# So this is asked, not guessed. The rule below is that doc's and
# `tools/formal_returnless_census.py`'s, and the census now calls THESE rather
# than keeping private copies, because a refusal and the measurement that sized
# it cannot be allowed to answer "does this function return" differently.
#
# The two primitives are separate because the census reports the halves
# separately and a third thing would be a second rule: a function that DECLARES
# a return type has said what it means even where the value is not CPython's
# (`def quiet(a) -> Int32: w = 1; return 0` agrees with CPython, and a
# declaration is the source's own statement that a value is coming), so it is
# out of scope here and the corpus measurement in the doc counts it apart.


def _value_return_exprs(fn) -> list:
    """The `value` of every `return` WITH a value in `fn`'s own body, at any
    depth.

    A nested definition is a different frame with its own returns, so the walk
    stops at one — the same rule "Read before store" uses for the same reason.
    Depth, not control flow: `if c: return 1` with a fall-through END is
    included, and it should be, because CPython returns `None` on the other path
    and `None` is still not a word.
    """
    out: list = []

    def scan(stmts) -> None:
        for st in stmts or []:
            kind = type(st).__name__
            if kind == "ReturnStmt":
                value = getattr(st, "value", None)
                if value is not None:
                    out.append(value)
                continue
            if kind in ("FunctionDef", "StructDef", "TraitDef",
                        "LambdaExpr"):
                continue
            for name in getattr(st, "__dataclass_fields__", ()) or ():
                child = getattr(st, name, None)
                if isinstance(child, list):
                    scan(child)

    scan(getattr(fn, "body", None) or [])
    return out


def fn_returns_a_value(fn) -> bool:
    """Whether `fn`'s own body has a `return` WITH a value, at any depth.

    Depth, not control flow: `if c: return 1` with a fall-through END answers
    True, and it should, because CPython returns `None` on the other path and
    `None` is still not a word. A function that returns a value on ONE path is
    a function whose result this path cannot represent either; what the refusal
    below is about is the function that has no value at all, because that is the
    case where the source never suggests one is coming.

    This is the PER-FUNCTION half and it is deliberately blind to the CALL GRAPH
    — a `return g()` counts as a value here because `g` might return one, and the
    reader that can see `g`'s body is `returnless_function_names`.
    """
    return bool(_value_return_exprs(fn))


def _return_expr_produces_no_value(expr, returnless: set) -> bool:
    """Whether a `return <expr>` produces the "no value" this path cannot carry.

    The DIRECT shape only: `return g(…)` where `g` is a bare-name call to a
    function already known to return nothing. An `expr` of any other shape — a
    call through a receiver, a dotted callee, a literal, an arithmetic term —
    produces a value, which is the conservative direction: an unrecognised shape
    leaves the function reading exactly as it did before.

    A `return v` through a LOCAL bound to such a call is deliberately NOT here.
    It needs the function's own binding table, which is a different walk, and it
    is the rarer of the two spellings; `return _err(msg)` is the one that occurs.
    """
    return (isinstance(expr, F.CallExpr)
            and isinstance(expr.func, F.IdentExpr)
            and expr.func.name in returnless)


def returnless_function_names(functions) -> set:
    """The names of the functions in `functions` whose CALLS produce no value,
    closing `fn_returns_a_value` over bare-name `return <call>` chains.

    `fn_returns_a_value` reads ONE body and answers for the returns it can see
    there; this is the same question one hop further out, and the hop is a real
    divergence rather than a refinement. `def f(a): return g(a)` where `g`
    returns nothing is a function whose result CPython evaluates to `None`, while
    this path leaves whatever the callee's last instruction wrote in the return
    register — so `print(f(1))` is the SAME silent wrong answer the direct
    `print(g(1))` is, reached through one `return` statement, and a reader that
    stops at the first hop builds the wrong program.

    **A LEAST fixed point, and that is what makes a cycle safe.** A pair that
    returns each other has no function that is PROVABLY value-less, so neither
    name enters the set and both read as returning a value — the direction that
    leaves an existing build unchanged. The predicate is monotone (a name known
    value-less only makes more returns value-less), so starting from the empty
    set and adding a name when every value-returning `return` is a call to a name
    already in it terminates at the smallest such set.

    A generator or coroutine is excluded, and so is a function that DECLARES a
    return type, both for the reason `function_returns_a_value` gives: the
    "value" is the object, and a declaration is the source saying a value is
    coming.
    """
    by_name: dict = {}
    for fn in functions:
        name = getattr(fn, "name", None)
        if isinstance(name, str):
            by_name[name] = fn
    returnless: set = set()
    changed = True
    while changed:
        changed = False
        for name, fn in by_name.items():
            if name in returnless:
                continue
            if (getattr(fn, "is_generator", False)
                    or getattr(fn, "is_async", False)
                    or fn_declares_a_return(fn)):
                continue
            exprs = _value_return_exprs(fn)
            if all(_return_expr_produces_no_value(e, returnless)
                   for e in exprs):
                returnless.add(name)
                changed = True
    return returnless


def fn_declares_a_return(fn) -> bool:
    """Whether `fn` STATES a return type — the ONE reader of that, and it
    delegates rather than repeating `declared_returns_a_value`'s test.

    `-> None` is not a return type here, for the reason that function gives: it
    is `void` at the ABI (`doc/ABI.md`'s scalar table), so it is read as no value
    rather than as one word that happens to be spelled `None`. The one case it
    adds is an EMPTY annotation — a `def f() -> :` states nothing, where the ABI
    reader's `str(rt).strip() in ("None", "NoneType")` test lets it through —
    and it is added HERE rather than there because that function's callers are
    the cross-module declaration paths (`external_declarations` parses another
    module's own header, where an empty annotation is not a spelling that
    occurs), while this one reads a body the parser has just produced.
    """
    rt = getattr(fn, "return_type", None)
    if isinstance(rt, str) and not rt.strip():
        return False
    return declared_returns_a_value(fn)


def _body_returns_a_value(fn, callee_returns_value) -> bool:
    """`fn_returns_a_value`'s walk, with an optional transitive reading.

    `callee_returns_value` is None for the source-only question and a callable
    `name -> bool` for the extended one. The extension is one case and it is
    the whole of what an intermediate function needs: `return f(…)` is a value
    for the source-only reader (there IS a `return` and it has an expression),
    but if `f` itself produces no value — the same `function_returns_a_value`
    question one call down — then the `return` hands back the very word this
    path cannot carry, so it is not a value-producing return either. Everything
    else an expression can be (a literal, an arithmetic expression, a call to a
    callee the resolver cannot answer for) is a value, which is the safe
    direction: an unrecognised shape keeps the answer the caller already had.

    The walk itself is `_value_return_exprs`'s (the shared reader), so this and
    `returnless_function_names` classify the same `return`s.
    """
    for v in _value_return_exprs(fn):
        if callee_returns_value is None:
            return True
        func = getattr(v, "func", None)
        if (isinstance(v, F.CallExpr) and isinstance(func, F.IdentExpr)
                and not callee_returns_value(func.name)):
            continue
        return True
    return False


def function_returns_a_value(fn, callee_returns_value=None) -> bool:
    """Whether a call to `fn` produces a value this path can carry.

    The conjunction of the two halves above, plus the two spellings whose
    "return value" is the OBJECT rather than a word: a generator yields and a
    coroutine awaits, so `def f(): yield 1` is not a function that returns
    nothing, and reading it as one would refuse every `for x in f(y)` in the
    corpus. The parser's own `is_generator`/`is_async` are the answer, for the
    reason `tools/formal_returnless_census.py` gives: they are the front end's
    decision and not a re-read of the body.

    **`callee_returns_value` carries the answer through a `return f(…)`, and it
    is a hook because "does `f` produce a value" is a question about ANOTHER
    function.** With it, `def h(): return g()` where `g` has no `return` is a
    function that produces nothing — CPython's `h(…)` is `None` — so a `print`
    of `h(…)` is refused by the same rule that refuses `print(g(…))` and
    `v = g(); print(v)`, one call deeper. Without it the answer is the
    source-only one and is unchanged, which is what the census and
    `ValueKinds.returns_a_value` ask for. The resolver is the emitter's job
    (`arm64_codegen`/`x86_64_codegen`'s `_callee_returns_value`), because the
    name→definition table lives there and a cycle has to be stopped there.
    """
    if getattr(fn, "is_generator", False) or getattr(fn, "is_async", False):
        return True
    if fn_declares_a_return(fn):
        return True
    return _body_returns_a_value(fn, callee_returns_value)


def function_returns_a_value_resolver(functions):
    """A `name -> bool` resolver for `function_returns_a_value`, over a
    `{name: FunctionDef}` table.

    The ONE implementation of the transitive half, so the two backends and the
    value-model test cannot answer "does `f` produce a value" three ways. The
    emitters build it over `self._functions` and hand it to the reader, which is
    why the table is an argument: the name→definition map is the emitter's and
    this file has no module index.

    A name that is not in `functions` answers True, and so does a name already on
    the recursion stack. Both are the safe direction — a value the source cannot
    be asked about (a linked module's export) and a cycle are each left with the
    answer the caller already had, where a wrong "no value" would refuse a
    program CPython runs.
    """
    def resolve(name, _seen=frozenset()):
        fn = functions.get(name)
        if fn is None or name in _seen:
            return True
        return function_returns_a_value(
            fn, lambda callee, _s=_seen | {name}: resolve(callee, _s))
    return resolve


def returnless_value_refusal(callee: str, rendering: str = "print()") -> str:
    """Why rendering the result of `callee(…)`, which returns nothing, is wrong.

    One message for both backends, and it is asked from `_print_call` in each of
    them rather than written twice, because that is the one position where a
    value this path cannot carry becomes TEXT: the arithmetic case computes with
    the word and the `x = f()` case is silent until somebody prints `x`, but a
    printed `None` is the shape CPython answers and the one a reader recognises.
    `printf` is the second such position and asks the same question through
    `returnless_printf_argument_refusal`, so `rendering` names which call is
    doing the rendering.

    The wording discipline is `string_concat_refusal`'s: name the callee, say
    what CPython answers, say what this path has instead, and say what to do. A
    reader told only "cannot tell" goes looking for something to look at, and
    there is nothing here to look at — the number the machine would print is not
    a number the source wrote.
    """
    return (
        f"{rendering} is asked to render the value of {callee}(…), and {callee} "
        f"returns nothing: CPython evaluates that call to `None` and prints "
        f"`None`, and a value on this path is one 64-bit word with no way to "
        f"say `no value` — the epilogue writes no return register, so the word "
        f"printed here would be whatever {callee}'s last instruction left "
        f"there, which is a number nothing in the source wrote (measured on "
        f"BOTH architectures from this source: CPython printed `None` where "
        f"this path printed `0`). Refused rather than emitted, because a "
        f"plausible number is worse than a refusal. Give {callee} a `return`, "
        f"or do not use its value"
    )


def returnless_printf_argument_refusal(name: str, args, no_value_callee_of):
    """The refusal for a printf vararg that renders a return-less call, or None.

    **`printf` is the other position where a value this path cannot carry
    becomes TEXT, and it was unguarded.** `print` builds its format from its own
    operands and refuses each of them in `_print_call`; a `printf` the SOURCE
    wrote was only checked for a usable FORMAT, so `printf("%d", g(…))` for a `g`
    with no `return` built and printed the leftover word — the same divergence
    `bugs/formal/FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_
    None.md` refuses for `print(g(…))`, at the same position (the value's word
    becoming text) and one call spelling away.

    `no_value_callee_of` is the caller's `ValueKinds` hook, the one reader of
    "this expression's value is the result of a function that returns nothing";
    it is passed in rather than re-derived so `print` and `printf` cannot answer
    that question differently. The format's index comes from
    `printf_format_arg_index`, so `sprintf`'s buffer argument is not mistaken for
    an operand. Both emitters ask this at the same line they ask the format
    check, so the two architectures cannot disagree about one call.
    """
    idx = printf_format_arg_index(name)
    if idx is None:
        return None
    for a in list(args)[idx + 1:]:
        callee = no_value_callee_of(a)
        if callee is not None:
            return returnless_value_refusal(callee, "printf()")
    return None


class ValueKinds:
    """What the names of one function hold, decided from its source.

    Built by scanning the function's statements once (twice, so a name bound
    from a name bound later still resolves), then queried per expression while
    a call is being lowered. Deliberately flow-INsensitive: a name bound to
    two different kinds in one function is recorded as undecidable, because
    picking either one would make the answer depend on which use site asked.

    The four hooks are what a backend has to supply, and they are what makes
    this a decision rather than a lowering:
      * `int_names` / `string_names` — the type annotations that mean an
        integer and a string. A parameter's annotation is the only thing that
        says what an unassigned name holds; without one it is a word, so an
        integer (see the note on kinds above).
      * `func_kind(name)` — the kind a call to a local function produces, from
        its declared return type or, failing that, from its return statements.
      * `slot_key(member_expr)` — the local-slot key for a field chain, so a
        struct field classifies like any other name.
      * `declared_kind(expr)` — what a FRAME SLOT holds, from the DECLARED type
        of the field, agreed over the holder's candidates.  Added for the case
        the other three cannot reach at all: a field read is not a name this
        function bound, and its kind is a fact about the struct's declaration
        rather than about this function's flow.  Without it every `len(self.x)`
        on a declared field was refused with "the source does not say what this
        operand holds" — false about a declaration, and for a list or string
        field the refusal was of something this path can answer.  See
        `declared_type_kind` for the whole of it; the hook is consulted only
        where the answer would otherwise be a guess, and a `None` from it leaves
        every existing decision exactly where it was.
      * `param_kind(name)` — what an UNANNOTATED parameter holds, agreed over
        every call site of this function in the image
        (`parameter_kinds_by_call_site`, which is the whole of the rule and
        the reader for it).  The sixth hook, and the one that closes the last
        place the "a word is an integer" default is a wrong answer rather than a
        safe one: `def f(s): if s:` called `f("")` answered 1 where CPython
        answers 0, because the empty string is a non-NULL pointer and
        `truthy_lowering`'s third row — the word itself — is right for every kind
        except this one.  The container row is that same evidence read for the
        BLOB a parameter is: `def total(xs): … len(xs) …` called
        `total([1, 2, 3, 4])` refused as "len() of a value classified as 'int'"
        about a list the same function subscripts, and an empty list handed to
        `if xs:` was truthy.  It is asked only where the parameter has no
        annotation, so an annotated parameter is never overridden, and `None`
        (the default) leaves every existing decision exactly where it was, which
        is why it is a hook and not a derivation.
      * `ctor_field_value(struct_name, call, field)` — the expression a
        CONSTRUCTION puts in a field's slot, or None.  The fifth hook, and it
        exists because `declared_kind` answers about the struct while a
        construction's arguments are about the CALL SITE, which is the only
        place the value is: `p = Point(3, 4)` gives field `x` an integer and a
        declaration says nothing about it (the common case has no annotation
        at all), while `p = Point(a, b)` where the arguments are this function's
        unannotated parameters gives nothing — and both were refused, by name,
        for the same sentence.  Measured on both architectures before this hook:
        `print("Point:", p.x, p.y)` on an unannotated two-field class refused
        with "print() cannot tell whether MemberExpr is a string or a number".
        `None` leaves every existing decision exactly where it was, which is
        why this is consulted after `declared_kind` and not instead of it.
      * `declared_is_dict(expr)` — whether a FRAME SLOT's field is declared a
        DICT.  `declared_kind`'s twin on the axis a kind cannot carry (all four
        container annotations are one word here), for the same reason
        `callee_is_dict` is separate from `func_kind`: `self.seen[k]` on a field
        declared `Dict[String, Int]` was refused with "the INDEX is a string and
        nothing in the source says what `self.seen` holds" — false about a
        declaration that is right there on the struct.  Asked only where the
        binding evidence has said nothing, and a `None` leaves every existing
        decision exactly where it was.  See `frame_slot_field_is_dict` for why
        this carries no value gate and `is_dict_value` for where it is read.
      * `float_names` — the vocabulary that makes a FLOAT a float rather than
        the word an integer is, and the only hook whose PRESENCE changes a
        default rather than refining one: an annotated parameter whose type is
        in it is `FLOAT_KIND`, where every other entry here either sets a kind
        from None or refines `INT_KIND`.  An `x: Float64` parameter arrives from
        the caller as one word, so the annotation is the only evidence there is
        of what those bits mean — the same argument `string_names` makes for
        `STR_KIND`.  Empty (the default) leaves every existing decision exactly
        where it was, which is why it is a hook and not a derivation.
      * `pointee_kind(expr)` — the KIND a POINTER DEREFERENCE yields, so
        `Int(p.value())` over a `Pointer[Float64]` is `FCVTZS` rather than a bit
        move.  A dereference's kind table answer would otherwise be the "a word
        is an integer" default, because a load is a word; the decision and the
        one reader are `pointee_kind_of`'s, and a `None` leaves every existing
        decision exactly where it was.
    """

    def __init__(self, fn, *, int_names=(), string_names=(), func_kind=None,
                 slot_key=None, declared_kind=None, ctor_field_value=None,
                 callee_is_dict=None, dict_names=("Dict", "dict"),
                 param_kind=None, declared_is_dict=None,
                 callee_returns_value=None, float_names=(), bool_names=(),
                 callee_is_bool=None, deref_kind=None,
                 pointer_pointee_kind=None, callee_returned_parameter=None):
        self._int_names = frozenset(int_names)
        self._fn = fn
        self._string_names = frozenset(string_names)
        # The THIRD vocabulary, and the only one whose presence changes a
        # default rather than refining one: an ANNOTATED parameter in
        # `float_names` is `FLOAT_KIND` (below), while every other vocabulary
        # entry here either sets a kind from None or refines `INT_KIND`. An
        # `x: Float64` parameter arrives from the caller as one word, so the
        # annotation is the only evidence there is of what those bits mean —
        # the same argument `STR_KIND`'s seeding below makes.
        self._float_names = frozenset(float_names)
        # The FOURTH vocabulary, and the only one whose PRESENCE changes nothing
        # about a KIND: `Bool` is `INT_KIND` here (`declared_type_kind` says so
        # and every arithmetic site is right about it), so this vocabulary is
        # recorded on its own map — `_bool_of` — and read only by
        # `is_bool_value`. Passing it is what lets the emitter say `print(flag)`
        # is CPython's `True`/`False` rather than this path's `1`/`0`; leaving
        # it empty claims nothing, which is the conservative direction.
        self._bool_names_vocab = frozenset(bool_names)
        self._func_kind = func_kind or (lambda name: None)
        self._param_kind = param_kind or (lambda name: None)
        self._slot_key = slot_key or (lambda expr: None)
        self._declared_kind = declared_kind or (lambda expr: None)
        # The hook that answers what a DEREFERENCE yields, and it is the one
        # kind question a load cannot answer from its own shape: a `p.value()`
        # is one word whether the pointee is an `Int64` or a `Float64`, so the
        # word's KIND has to come from the pointee's declaration.  It returns
        # `FLOAT_KIND` for a float pointee and `None` for everything else, which
        # is the direction that leaves every existing decision where it was:
        # without it a deref falls to the "an extern returns a word" default and
        # is an integer.  See `FLOAT_POINTEE_NAMES` and `POINTEE_WIDTHS`.
        self._pointer_pointee_kind = pointer_pointee_kind or (
            lambda expr: None)
        # The dict-ness twin of the line above, and consulted only where
        # `_dict_names` has nothing to say — see the hook's own paragraph.
        self._declared_is_dict = declared_is_dict or (lambda expr: None)
        self._ctor_field_value = ctor_field_value or (
            lambda struct_name, call, field: None)
        # The pointee's kind, so a DEREFERENCE expression carries the kind of
        # what it loads rather than the "a word is an integer" default.  The
        # seventh hook, and the only one whose whole job is to let one value's
        # kind flow: `Int(p.value())` over a `Pointer[Float64]` is `FCVTZS` and
        # not a bit move, which is why the pointee stopped being refused by name.
        # A `None` leaves every existing decision exactly where it was.  The
        # decision is `pointee_kind_of`'s; the backend binds the tables it needs.
        self._pointee_kind = pointee_kind or (lambda expr: None)
        # The SIXTH hook, and the one the KIND axis cannot express: whether a
        # call to a function of this module produces a DICT. A dict and a list
        # are the same word pointing at the same blob header on this path, so
        # `kind_of` answers "list prefix" for both and every other hook here is
        # silent about the difference — while `d["a"]` reads a key out of one
        # and an ELEMENT OFFSET out of the other. See `is_dict_value`.
        self._callee_is_dict = callee_is_dict or (lambda name: False)
        # …and its BOOL twin, asked by `is_bool_value` for the same reason and
        # read the same way: the declared return type of a function of this
        # module, which only the emitter's table holds. `None` (this class's
        # "cannot say") rather than False for a callee nothing can answer for.
        self._callee_is_bool = callee_is_bool or (lambda name: None)
        # …and the hook that lets a call hand a FOREIGN-BYTES argument straight
        # back: the positional index of a parameter the callee returns
        # unchanged (`model.returned_parameter_position`), or None. It is the
        # RETURNED spelling of `FOREIGN_BYTES_KIND`'s gap — the kind rides on
        # the expression and is lost at a call, and this is the one call whose
        # result is forced to be the argument's provenance.
        self._callee_returned_parameter = callee_returned_parameter or (
            lambda name: None)
        self._dict_names_vocab = frozenset(dict_names)
        self.locals: dict = {}
        self._conflicts: set = set()
        self._returns: set = set()
        # `xs.append(...)` receivers, scanned once from the function's own
        # body.  A list literal's element kind describes the list only until
        # something appends to it, so the subscript-evidence arm in
        # `scalar_container_base_evidence` has to ask this before it treats
        # `own_shape_kind` as a claim.  Lazy rather than eager: most functions
        # never ask, and the scan is the whole statement tree.
        self._appended_names = None
        # The DICT-NESS axis, parallel to `locals`: `{name: True|False}` for the
        # names this function's own statements bound to a dict (or to something
        # that is not one), and `return_is_dict` below for the function's RETURN
        # statements. Unanimity, like every other map in this class: a name two
        # statements disagree about is not in here at all, so a caller reads
        # None and keeps whatever it did before.
        self._dict_names: dict = {}
        self._dict_conflicts: set = set()
        self._returns_dict: set = set()
        # The BOOL axis, parallel to `_dict_names` and for the same reason: a
        # `Bool` on this path is a word holding 0 or 1, so its KIND is
        # `INT_KIND` (`declared_type_kind`) and every arithmetic site, `len` and
        # comparison is right about that. What a KIND cannot carry is the one
        # thing about a bool that is observable — CPython prints `True`/`False`
        # where this path printed the word as a decimal, on both architectures,
        # for a literal, a comparison, a `not`, a `Bool`-annotated parameter and
        # a `Bool`-annotated local alike. So it is a separate map read by
        # `is_bool_value`, built from the same evidence `_dict_names` is (a
        # declared annotation) plus the two shapes `bool_valued_shape` needs no
        # table for, and with the same UNANIMITY rule: a name two statements
        # disagree about is not in here at all.
        self._bool_of: dict = {}
        self._bool_conflicts: set = set()
        # …and the `None` axis, the third and last of this family. `None` has no
        # representation on this path at all (a value is one 64-bit word and
        # this one is the absence of one), so the ONLY correct renderings are
        # the ones that are decided at build time: `print(None)` and, for a name
        # every statement binds to `None`, `print(n)`. `n = None; print(n)`
        # printed `0` on both architectures — a green build and a number nobody
        # wrote — so the binding is recorded here rather than guessed at the use
        # site.
        self._none_of: dict = {}
        self._none_conflicts: set = set()
        # …and the FOURTH, which is a KIND-shaped fact the kind table does not
        # carry rather than a spelling: a `bytes` literal is `STR_KIND` here (it
        # is a `char *` to interned bytes like any other text), and every
        # operation that asks a kind is RIGHT about that — `len`, `==`, `in` and
        # `startswith` all agree with CPython on a `bytes` because a `bytes` and
        # a `str` of the same characters compare and measure the same. The one
        # operation that does NOT is `print`, which writes CPython's `repr(b)` —
        # `b'ab'`, never `ab` — and that is a rendering decision rather than a
        # type, so it gets the same narrow reader as the bool axis.
        self._bytes_of: dict = {}
        self._bytes_conflicts: set = set()
        # Per name, the kinds the statements of this function bound it to BY
        # THE EXPRESSION'S OWN SHAPE — `kind_of` and nothing else, so no
        # "unclassified means a word, and a word is an integer" default ever
        # enters it.  `own_shape_kind` reads this, and the difference is the
        # whole of what separates "the source SAYS this name holds an
        # integer" from "we could not classify it"; see that method.
        self._own_shape: dict = {}
        # The CONSTRUCTIONS that bound a name in this function's body, keyed by
        # name — `{(callee, call)}`, and a `None` VALUE as the tombstone for a
        # name some other statement also binds.  It is the evidence
        # `_constructed_field_kind` reads, and the tombstone is the reason that
        # reading is sound under a flow-INsensitive map: `p = Point(3, 4)` and
        # then `p = something_else` leaves one name with two homes, and a kind
        # read off the construction would be a claim about the first
        # instruction rather than about the slot.  Keyed by the call's identity
        # because the scan runs twice and a list would collect each site twice.
        self._ctor_calls: dict = {}
        # The fields of a holder this function WRITES THROUGH, which retracts
        # the construction's claim about that field and only that field.  See
        # `_note_field_stores`, which carries the measurement that makes it
        # load-bearing rather than tidy.
        self._field_stores: dict = {}
        # The dict LITERAL that bound a name in this body — the node itself, or
        # a `None` tombstone for a name something else binds.  Same shape and
        # same reason as `_ctor_calls`, for the same flow-insensitivity: the
        # value kind of a SUBSCRIPT is a claim about one element word, and the
        # only thing that says whether that word was written is the initializer
        # this function itself ran.  See `_note_dict_init`.
        self._dict_inits: dict = {}
        # The names this body bound to a call that produces NO value — the
        # callee's name, or a `None` tombstone for a name something else binds.
        # Same shape and same reason as `_ctor_calls` and `_dict_inits`, and the
        # shape is the point: `v = g()` where `g` returns nothing leaves `v`
        # holding a word that is not any value, and `print(v)` is where CPython
        # says `None` and this path would print whatever `g` left behind. One
        # binding statement is enough to retract the claim, so the map is
        # order-independent in the same way `_ctor_calls` is. See
        # `_note_no_value_call` and `no_value_callee_of`.
        self._no_value_calls: dict = {}
        # …and the hook that decides whether a CALLEE produces one. It is a hook
        # and not a lookup because the answer is about ANOTHER function, which
        # is the emitter's question (`_callee_kind` beside it answers the same
        # way about kinds, and the stack that stops it recursing is the
        # emitter's too). The DEFAULT is the safe direction — a callee nothing
        # can answer for is one this map says nothing about, so every caller
        # keeps the answer it had.
        self._callee_returns_value = callee_returns_value or (
            lambda name: True)
        # The EIGHTH hook, and the one that lets a POINTER DEREFERENCE carry a
        # kind: `pointer_deref_kind` answers `FLOAT_KIND` for a `p.value()`
        # whose pointee is a float, and `None` for everything else.  A
        # dereference is an EXPRESSION the whole-function scan never binds — it
        # is not a name, a field, a constructor or a subscript — so no existing
        # hook can reach it, and without one `Int(p.value())` over a
        # `Pointer[Float64]` read the exponent field.  Asked from `kind_of`'s
        # CallExpr arm, where the dereference arrives.
        self._deref_kind = deref_kind or (lambda expr: None)
        # The names this function's SIGNATURE binds, kept apart from the ones
        # its body binds, and the reason is the `declared_kind` hook: an
        # unannotated parameter is seeded INT_KIND above, and for a METHOD
        # receiver that default is the one thing the declaration can improve on
        # — `self` of a one-field struct IS that field, so its kind is the
        # field's declared kind and not "a word, therefore an integer".  A name
        # the BODY bound is a different question: flow decided it, and flow
        # wins.
        # The recursion cut-off `_element_kind_in_flow` uses; see that method.
        self._resolving = False
        self._param_names: set = set()
        for pname, pann in _param_list(fn):
            self._param_names.add(pname)
            # An unannotated parameter is a word arriving from the caller, and
# a word is an integer here (see the note on kinds above).  The
            # exception is a word the CALL SITES agree is a `char *`, which the
            # `param_kind` hook carries: without it `def f(s): if s:` called
            # `f("")` printed 1 where CPython prints 0, on both architectures,
            # because the empty string is a non-null pointer and the identity
            # test is the right answer for every kind except this one.  An
            # ANNOTATED parameter is not overridden — the annotation is a
            # statement about the value and the call sites are evidence about
            # the calls — which is why the hook is asked only in the `else`.
            if pann in self._string_names:
                self.locals[pname] = STR_KIND
            elif pann in self._float_names:
                self.locals[pname] = FLOAT_KIND
            elif pann:
                self.locals[pname] = INT_KIND
            else:
                self.locals[pname] = self._param_kind(pname) or INT_KIND
            # …and the dict axis, which the kind above cannot carry: a
            # `Dict[String, Int]` parameter and a `List[Int]` one are the same
            # kind here and opposite answers to `d["a"]`.  A parameter has no
            # BINDING statement for the scan to see, so this annotation is the
            # only evidence there is for it.
            if declared_type_is_dict(pann, self._dict_names_vocab):
                self._dict_names[pname] = True
            # …and the two axes that have no KIND at all. A `Bool` parameter is
            # `INT_KIND` above and stays there — it is a word holding 0 or 1 —
            # but it PRINTS as `True`/`False`, and that is a fact about the
            # declaration only this loop can see: a parameter has no binding
            # statement for `_scan` to read. Unanimity is not a question here
            # (a parameter is bound once, by the signature) so this records
            # unconditionally, which is the same rule `_param_names` follows.
            if annotation_is_bool(pann, self._bool_names_vocab):
                self._bool_of[pname] = True
        # …and the BRACKET parameters, which are parameters with a home and a
        # declaration and are NOT in `params` -- `def f[T: AnyType, keys:
        # List[T]](base: Int)` has `keys` in the bracket block alone.  The
        # bracket block recorded the name and the default and used to throw the
        # TYPE away, so nothing here had an annotation to read and a bare `keys`
        # was an unclassified word: `len(keys)` was refused with "the source does
        # not say what this operand holds" in a body where `keys[0]` in the same
        # function lowered, because the subscript's base classifier reads the
        # declaration and this did not.  Two readers of one word consulting
        # different evidence is how a disagreement becomes a wrong answer rather
        # than a refusal, so they are the same evidence now.
        #
        # EVERY bracket parameter is added to `_param_names`, TYPE parameters
        # included, because the split is not the parser's to make and this loop
        # does not need it: a bracket parameter's kind is whatever
        # `declared_type_kind` maps its annotation to, and a TYPE parameter's
        # annotation is a trait or a width (`AnyType`, `DType`, `SIMDSize`,
        # `CompilationTarget`) — none of which names something this path has a
        # representation for, so it maps to None and claims nothing.  The
        # discrimination is therefore self-selecting: only an annotation that
        # names a container or a string produces a kind, and those are exactly the
        # ones `len()` and a subscript can act on.
        for _pname, _pann in bracket_value_params(fn):
            self._param_names.add(_pname)
            _kind = declared_type_kind(
                _pann, self._int_names, self._string_names,
                None, float_names=self._float_names)
            if _kind is not None:
                self.locals[_pname] = _kind
            if declared_type_is_dict(_pann, self._dict_names_vocab):
                self._dict_names[_pname] = True
            if annotation_is_bool(_pann, self._bool_names_vocab):
                self._bool_of[_pname] = True
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
        # …and the same rule on the dict axis: every `return` in this function
        # has to say "a dict" for the function to produce one. One return that
        # does not is enough to withhold the answer, because a function that
        # returns a dict on one path and a list on another has no shape for
        # `d["k"]` and guessing is the fault this axis exists to remove.
        self.return_is_dict = self._returns_dict == {True}
        # Whether this function produces a value at all — the question
        # `returnless_value_refusal` is about, and a different one from
        # `return_kind`: a function with no `return` has no kind to be
        # undecided about, it has NO RESULT, and `return_kind`'s INT_KIND
        # default above is exactly the word-that-is-not-a-value this axis exists
        # to name. Read through the SHARED `function_returns_a_value` rather than
        # off `_returns` alone, because a declared return type and a generator's
        # `yield` are both statements that a value is coming and neither is a
        # `ReturnStmt` in this body.
        self.returns_a_value = function_returns_a_value(fn)



    # ── scanning ───────────────────────────────────────────────────────

    def _bind(self, name, kind, own=None) -> None:
        if name in self._conflicts:
            return
        if own is not None:
            self._own_shape.setdefault(name, set()).add(own)
        if name in self.locals:
            if self.locals[name] != kind:
                # Bound two ways in one function: refuse rather than answer
                # with whichever use site asked first.
                self.locals[name] = None
                self._conflicts.add(name)
                # …and no own-shape claim either, for the same reason: two
                # statements that disagree about what a name holds are exactly
                # the case where "the source says integer" is not available.
                self._own_shape.pop(name, None)
            return
        self.locals[name] = kind

    def _bind_value(self, name, value, ann=None) -> None:
        """Bind `name` to what `value` holds — `_kind_with_ann` then `_bind`,
        and record what the statement says about it on the three axes a KIND
        cannot carry.

        Four independent pieces of evidence about one binding, so four calls and
        not one: the annotation reader can improve the KIND of a value that
        classified to nothing, and it says nothing about dictness, boolness or
        `None`-ness at all, while each of those readers must keep doing so for
        the names the annotation never touches. The three axes are the same
        shape as `_bind_dictness` and share its rule — see
        `_bind_spelling`.

        **The bool axis reads the VALUE and not `ann`, and that is a decision
        rather than an omission.** An annotation is metadata about what the name
        is FOR (`_kind_with_ann`'s own reading) while the value is a direct
        statement about what flows into it, and on THIS axis the annotation is
        the weaker of the two:

            b: Bool = True     ->  the value is a `BoolLiteral`: True
            t = a > b          ->  the value is a comparison: True
            b = flag()         ->  the value is a `-> Bool` call: the hook
            b: Bool = 5        ->  the value is an `IntLiteral`: nothing

        and the last row is why the annotation is not consulted: CPython's
        annotation does not convert, so `print(b)` is `5` and an annotation that
        said True would be a wrong answer dressed as a declaration. A parameter
        is the other shape and keeps its annotation (`__init__`'s loop), because
        a signature binds a name no statement binds and the annotation is
        genuinely all the evidence there is.
        """
        kind, own = self._kind_with_ann(value, ann)
        self._bind(name, kind, own=own)
        self._bind_dictness(name, self.is_dict_value(value))
        self._bind_spelling(name, self._bool_of, self._bool_conflicts,
                            self.is_bool_value(value))
        self._bind_spelling(name, self._none_of, self._none_conflicts,
                            self.is_none_expression_of(value))
        self._bind_spelling(name, self._bytes_of, self._bytes_conflicts,
                            self.is_bytes_value(value))

    def is_none_expression_of(self, value):
        """True / False / None: whether `value` IS / is NOT / is not stated `None`.

        The tri-state `is_none_value` records, asked about a statement's VALUE
        rather than about an expression at a use site. The `False` arm is what
        makes the axis's unanimity rule reachable — without it every non-`None`
        initializer is "no statement", the first binding's `True` stands, and
        `n2 = None` then `n2 = 5` then `print(n2)` prints `None` where CPython
        prints `5` (measured on both architectures before this arm existed).

        It is `_NOT_NONE` and not "not `None`", for `_bind_dictness`'s reason: a
        literal's other-ness is a fact and an unclassified expression's is not.
        """
        if is_none_expression(value):
            return True
        if isinstance(value, self._NOT_NONE):
            return False
        return None

    def _bind_spelling(self, name, table: dict, conflicts: set,
                       answer) -> None:
        """Record what a statement says about `name` on an axis with no KIND.

        `_bind_dictness` generalised, and it is one function for the three axes
        rather than three copies because the RULE is the whole of each and it is
        the same rule three times: unanimity. Two statements that disagree leave
        the name out of `table` entirely and in `conflicts`, so the reader
        (`is_bool_value`, `is_none_value`) answers None and every caller keeps
        what it did before. Recording `False` for a statement that says
        "not this" is what makes that work — without it a name bound first to
        `None` and then to a dict would keep the `None` answer, which is the same
        trap `locals` avoids with `_conflicts`, and the same trap in the same
        place.

        `answer` is tri-state: True/False is a statement, None is no statement
        at all. An axis whose evidence is a DECLARATION (`_bool_of`, from an
        annotation) passes None for a statement with no annotation, and an axis
        whose evidence is a VALUE (`_none_of`, from `is_none_expression`) passes
        None for a value that is not `None`. Both are the conservative
        direction, and neither is "not this" — claiming a name is not a bool
        because a statement did not annotate it would refuse to print the bool
        of a name that plainly is one.
        """
        if name in self._conflicts or answer is None:
            return
        if name in conflicts:
            return
        if name in table:
            if table[name] is not bool(answer):
                table.pop(name, None)
                conflicts.add(name)
            return
        table[name] = bool(answer)

    def _note_spelling_axis(self, target, value) -> None:
        """Record `target`'s two axis claims, for a statement that binds a TARGET.

        The `_bind_value` pair of axis records, for the `AssignStmt` arm of
        `_scan`, which binds through `_bind_target` and therefore never reaches
        it. One level deep into the target, and for the reason
        `_unpacked_element_kind` is asked in the same arm: `a, b = x, y` binds
        two names, and a container target is the same statement with more of
        them — and a container target's per-element VALUE is not the container,
        so the elements are asked about `None` and claim nothing. A
        `MemberExpr` target (`self.flag = True`) is a FIELD, not a name this
        function binds, and a field's declared type is the `declared_kind`
        hook's question rather than this one's — so it claims nothing here,
        which is the conservative direction and leaves `print(self.flag)` as it
        was.
        """
        if isinstance(target, F.IdentExpr):
            self._bind_spelling(target.name, self._bool_of, self._bool_conflicts,
                                self.is_bool_value(value))
            self._bind_spelling(target.name, self._none_of,
                                self._none_conflicts,
                                self.is_none_expression_of(value))
            self._bind_spelling(target.name, self._bytes_of,
                                self._bytes_conflicts,
                                self.is_bytes_value(value))
        elif isinstance(target, (F.TupleExpr, F.ListExpr)):
            for el in (getattr(target, "elements", None) or []):
                self._note_spelling_axis(el, None)

    def _bind_dictness(self, name, answer) -> None:
        """Record what a statement says about `name` on the DICT axis.

        Unanimity, and it is the only rule: two statements that disagree leave
        the name out of `_dict_names` entirely, so `is_dict_value` answers None
        and every caller falls back to what it did before. Recording `False` for
        a non-dict binding is what makes that work — without it a name bound
        first to a dict and then to a list would keep the dict answer, which is
        the same trap `locals` avoids with `_conflicts`.

        A `_bind_spelling` call and not the body it used to have, since that
        function is now the one copy of the rule for all three axes of this kind
        (dictness, boolness and `None`-ness).
        """
        self._bind_spelling(name, self._dict_names, self._dict_conflicts,
                            answer)

    def _kind_with_ann(self, value, ann=None):
        """`(kind, evidence)` for a binding, with the DECLARED type folded in.

        `ann` is the `type_ann` of the statement doing the binding, and it is
        read only to IMPROVE an answer the value could not give.  That is the
        whole of the rule and it is one-directional on purpose: the value's own
        shape is a direct statement about what flows into the name, while the
        annotation is metadata about what the name is FOR — which is the reading
        `formal/build.py`'s `AssignStmt` arm already takes ("type_ann is
        metadata, not a storage decision").  So an annotation can replace a
        DEFAULT and never a claim, and `var x: String = 5` still classifies as
        the integer the literal says it is.

        The case this exists for is the one where the default was the only thing
        there was.  Measured, both architectures, before this reader:

            from os.path import dirname, abspath

            HERE = dirname(abspath(__file__))          # a module-global slot

            def main(n):
                s: String = HERE                       # annotated String
                print(s)                               # -> 105553157226576

        `HERE` is a module-level name holding a `char *`, so it is not a local
        of `main` and `global_slot_kind` claims nothing about it (`_body_store_shape`
        asks only of a bare-name callee, deliberately); `kind_of` then returned
        None, `_value_kind` turned that into `INT_KIND` — this model's default
        for a word — and `print` rendered the interned path as a DECIMAL.  A green
        build, an exit status of 0, and an address printed as though it were the
        string.  The declaration is in the source and says `String`; the reader
        for it is `_annotation_kind`, which is the same vocabulary test
        `_param_list`'s parameter seeding uses so a parameter and an annotated
        assignment of the same spelling cannot answer differently.

        BOTH statement forms are covered and that is not tidiness: `var d: T = x`
        parses as a `VarDecl` while `d: T = x` — the same text without the
        keyword, and the spelling this repository's own files use — parses as an
        `AssignStmt` carrying a `type_ann`.  Only the `AssignStmt` arm reached
        the reader at first, which is why the measurement above was still an
        address after the first attempt.
        """
        own = self._own_shape_of(value)
        kind = self._value_kind(value)
        if own is None and ann is not None:
            declared = self._annotation_kind(ann)
            if declared is not None:
                kind, own = declared, declared
        return kind, own

    def _annotation_kind(self, ann):
        """What a declared type says a name holds, or None.

        The vocabulary test `_param_list`'s parameter seeding uses — `int_names`
        and `string_names` are the build's own annotation vocabularies, read
        from `formal/types.py` by both backends — and it answers None for
        everything else, which is the safe direction: a container annotation
        (`List[Int]`), a `-> T` return type in a position that is not a
        declared type, and a name that is not in either vocabulary leave the
        value's own classification exactly as it was.

        `String` is the only annotation that changes an answer, and that is not
        an accident of this path: a string here is a `char *` and an integer
        here is a word, so the two are indistinguishable except by a
        declaration — which makes the declaration the only evidence there is,
        and makes `None` for everything else the conservative answer rather than
        the convenient one.
        """
        text = ann.strip() if isinstance(ann, str) else None
        if not text:
            return None
        if text in self._string_names:
            return STR_KIND
        if text in self._float_names:
            return FLOAT_KIND
        if text in self._int_names:
            return INT_KIND
        return None

    def _own_shape_of(self, value):
        """`kind_of(value)`, or None when that answer is a fallback.

        The one place `own_shape_kind`'s evidence is filtered, and the filter is
        a CALL. What a call produces is a fact about the CALLEE, and this model
        has two answers for it with no way to tell them apart here: a declared
        return type, or — when the callee declares nothing, or its returns
        could not be classified, or it is not a function of this unit at all —
        the same "a word, therefore an integer" default everywhere else. The
        `func_kind` hook is a black box by construction (it exists because
        `ValueKinds` cannot see the unit's function table), so `kind_of` cannot
        say which of the two produced `INT_KIND`, and a claim of "the source
        says this name holds an integer" may not rest on it.

        Measured, both architectures, before this filter: a `get(self) ->
        List[Int]` method's result bound to a local and then subscripted built
        and answered 2, and this filter is what keeps it that way.

        The residual is real and it is stated rather than papered over: `a = f()`
        followed by `a[0] = 1` is not refused here, and still faults at run
        time the way it did before any of this. Narrowing an over-refusal is
        what was bought; a class that was never caught is not made worse.
        """
        if isinstance(value, F.CallExpr):
            return None
        return self.kind_of(value)

    def _value_kind(self, value):
        """`kind_of(value)`, or INT_KIND when it is unclassified and is not a
        container. A list/dict/set literal, or anything already known to be a
        blob, keeps its kind: printing one of those as a number would print a
        frame address."""
        kind = self.kind_of(value)
        if kind is None:
            if not _is_container_literal(value):
                return INT_KIND
        return kind

    def _bind_for_target(self, target, kind, own=None) -> None:
        """Bind a `for` target's names, one level DOWN from the element.

        `kind`/`own` are the kind and own shape of ONE ELEMENT of the iterable —
        what `_iterable_kind`/`_iterable_own_shape` answer — and that element is
        what a SMALL target (`for x in …`) binds directly.  A TUPLE target
        UNPACKS that element, so each of its fixed names holds one element of
        it: `subscript_element_kind(kind)` and not `kind` itself, which is the
        narrowing the assignment path already applies
        (`_unpacked_element_kind`) and this path was missing.  Measured, both
        architectures, before this method: `for a, b in [(1, 2)]: printf("%d",
        a)` refused with the `%d`-reads-a-CONTAINER sentence, because `a` was
        classified as `list:int` — the kind of the whole TUPLE the loop binds —
        where the source plainly says it holds an integer.  A trailing `*rest`
        is the one target that IS a container: it holds the tail as a blob, so
        it keeps `kind`, and its names are bound with the same rule the small
        target uses.

        A NESTED group recurses with the SAME `kind`, for the reason above it:
        a group is an element of the element, and the only kind the model has
        for it is the one the whole element carries (a homogeneous nesting such
        as `for a, (b, c) in [(1, (2, 3))]` states it either way).  That is the
        conservative direction — a group whose element kind the model cannot
        state keeps the container claim the flat reader gave every leaf, so no
        program that read a group's tail as a blob stops doing so."""
        tree = for_target_tree(target) if isinstance(target, str) else target
        if isinstance(tree, str):
            name = tree[1:].strip() if tree.startswith("*") else tree
            self._bind(name, kind, own=own)
            return
        if isinstance(tree, list):
            for child in tree:
                if isinstance(child, list):
                    self._bind_for_target(child, kind, own=own)
                    continue
                if isinstance(child, str) and child.startswith("*"):
                    self._bind(child[1:].strip(), kind, own=own)
                    continue
                self._bind(child,
                           subscript_element_kind(kind) if kind else None,
                           own=subscript_element_kind(own) if own else None)
            return
        self._bind_target(tree, kind, own=own)

    def _bind_target(self, target, kind, own=None) -> None:
        """Bind whatever names an assignment target introduces."""
        if isinstance(target, F.IdentExpr):
            self._bind(target.name, kind, own=own)
        elif isinstance(target, (F.TupleExpr, F.ListExpr)):
            for el in target.elements:
                self._bind_target(el, kind, own=own)
        elif isinstance(target, str):
            for nm in _target_names(target):
                self._bind(nm, kind, own=own)

    def _note_construction(self, target, value) -> None:
        """Record (or retract) the construction evidence a binding gives.

        A construction is `target = <call to a bare name>` — a type
        constructor, since a call to a name that is not a type is answered by
        `func_kind` instead and the hook returns None for it anyway. Everything
        else that binds the name is a RETRACTION: the name then has a home this
        map cannot describe, and a field kind read off the construction would be
        a claim about the construction site rather than about the slot. So a
        tombstone is written, and a tombstone is what a later construction does
        not overwrite (`setdefault`), which makes the answer order-independent
        rather than a function of where in the body the two bindings sit.

        A `str` target (a `VarDecl`'s name) and a tuple target are both
        refusals here for the same reason: `_bind_target` splits them, and the
        construction evidence wants ONE name."""
        name = target if isinstance(target, str) else (
            target.name if isinstance(target, F.IdentExpr) else None)
        if name is None:
            return
        if isinstance(value, F.CallExpr) and isinstance(value.func,
                                                        F.IdentExpr):
            if name not in self._ctor_calls:
                self._ctor_calls[name] = {}
            sites = self._ctor_calls[name]
            # A tombstone is not replaced by a later construction, which is what
            # makes the answer independent of where in the body the two bindings
            # sit — so this reads the existing entry rather than `setdefault`ing
            # one.  The `in` test above is what tells an ABSENT entry from a
            # tombstone: `dict.get` answers None for both, and conflating them
            # silently dropped every construction with no retraction before it,
            # which is measured and pinned in `test_formal_value_model.py`'s
            # `a_constructed_field_prints` — a whole evidence source that reads
            # as "this function constructs nothing".
            if sites is not None:
                sites[id(value)] = (value.func.name, value)
        else:
            self._ctor_calls[name] = None

    def _note_dict_init(self, target, value) -> None:
        """Record (or retract) the dict literal that gives a name its elements.

        The evidence `dict_literal_key_value_kind` is asked about, and the reason
        it is kept beside `_ctor_calls` rather than inside it is that the two
        answer different questions: a construction says what a FIELD's slot
        holds, and a dict literal says which element WORDS were written. The
        second is the only thing that can answer "was the key this subscript
        uses one of them", which is the gate the whole of this is built on.

        The tombstone rules are `_ctor_calls`' and they are not tidiness. A name
        bound to a dict literal and then to something else has two homes, and a
        kind read off the first is a claim about one instruction; two dict
        literals for one name are the same problem in a different shape, so the
        second one also tombstones. And the scan runs twice over the same
        statements, so identity — not equality — is what says "the same
        statement", which is why the value stored is the NODE and the test is
        `is`.
        """
        name = target if isinstance(target, str) else (
            target.name if isinstance(target, F.IdentExpr) else None)
        if name is None:
            return
        if isinstance(value, F.DictExpr):
            if name not in self._dict_inits:
                self._dict_inits[name] = value
            elif self._dict_inits[name] is not value:
                self._dict_inits[name] = None
        elif name in self._dict_inits:
            self._dict_inits[name] = None

    def _note_no_value_call(self, target, value) -> None:
        """Record (or retract) the evidence that a name holds an EMPTY result.

        `target = g(…)` where `g` returns nothing is the only shape recorded, and
        the callee has to be a BARE NAME: a call through a receiver (`self.f()`)
        binds a method, whose body this table does not have, and a dotted callee
        (`mod.f()`) is a name this unit did not compile. Answering for either
        would be the by-name mistake `formal/build.py`'s returned-frame table
        documents — "a name whose definitions disagree is absent from it" — with
        no table here to hold the disagreement.

        The tombstone is `_ctor_calls`' and `_dict_inits`' rule and is the reason
        this is not a flow analysis: `v = g()` and then `v = 5` leaves one name
        with two homes, and a claim read off the first is a claim about one
        instruction. **A RETRACTION always wins and a claim never does**, which
        is the one place this map's rule differs from `_ctor_calls`' and it is
        the difference that matters here: that map keys sites by identity and
        only needs a later binding to stop a SECOND construction from being
        claimed, while this one asks a question about the name as a whole ("every
        binding of `v` in this function is a call that produces no value"), so
        the first `v = 5` has to end it whatever came before. Two calls that
        both produce no value are still one claim, hence the claim's own
        first-wins rule — and both rules are order-INDEPENDENT, which is what
        makes the two scan passes (they visit the same statements in the same
        order) agree rather than drift.

        A name in `_conflicts` is left alone: two statements that disagree about
        what it holds have already made it undecidable, and this axis adds
        nothing to that.
        """
        name = target if isinstance(target, str) else (
            target.name if isinstance(target, F.IdentExpr) else None)
        if name is None or name in self._conflicts:
            return
        if (isinstance(value, F.CallExpr) and isinstance(value.func, F.IdentExpr)
                and not self._callee_returns_value(value.func.name)):
            self._no_value_calls.setdefault(name, value.func.name)
        else:
            self._no_value_calls[name] = None

    def no_value_callee_of(self, operand):
        """The callee whose EMPTY result `operand` is, or None.

        The one reader of "does this expression carry a value at all", and it
        answers for the two shapes a `print` can be handed: the call itself
        (`print(g(1, 2))`) and a local whose every binding in this function is
        such a call (`v = g(1, 2); print(v)`). The second shape is why this is
        not a single `isinstance` test at the print site, and it is asked of the
        map `_note_no_value_call` filled rather than of the body, so the print
        decision and the scan cannot disagree about which binding it was.

        None for everything else, which is the direction that matters: a caller
        that reads None keeps the answer it had, so an expression this does not
        recognise is rendered exactly as before.
        """
        if isinstance(operand, F.CallExpr) and \
                isinstance(operand.func, F.IdentExpr):
            name = operand.func.name
            return None if self._callee_returns_value(name) else name
        if isinstance(operand, F.IdentExpr):
            return self._no_value_calls.get(operand.name)
        return None

    def _note_field_stores(self, target) -> None:
        """Record that a statement writes THROUGH a holder's field.

        Per FIELD rather than per holder, because the claim is per field: `p` is
        a frame, a store to one of its slots changes that slot and no other, and
        `p = P("hi", 7); p.n = 8; print(p.s)` still has an answerable `p.s`.

        It has to exist at all. The construction says what went into the slot
        WHEN THE OBJECT WAS BUILT, and a statement after it in the same
        function can put something else there — which is not a theoretical gap.
        Measured on both architectures, from a GREEN build, with nothing in the
        image wrong:

            class P:
                def __init__(self, s, n):
                    self.s = s
                    self.n = n
            def main():
                p = P("hi", 7)
                p.s = 5
                print("s:", p.s)

        → SIGSEGV, exit 139, both architectures. `p.s` classified as a string
        from the construction, `p.s = 5` made it the integer 5, and `%s` walked
        bytes at address 5 looking for a NUL — the same fault
        `test_formal_value_model.py`'s `a_percent_s_of_an_integer_is_refused`
        exists to keep out, reached through a field rather than through a name.

        Depth 1 only, and the reason is the same one `declared_kind` documents:
        `a.b.c = v` writes the slot of the frame `a.b` names, not a slot of the
        frame `a` names, so it says nothing about `a`'s own words. A SUBSCRIPT
        store (`p.items[0] = x`) writes through a pointer and changes no word of
        `p` either, which is why neither shape is recorded."""
        if isinstance(target, (F.TupleExpr, F.ListExpr)):
            for el in target.elements or []:
                self._note_field_stores(el)
            return
        if not isinstance(target, F.MemberExpr) or not isinstance(
                target.obj, F.IdentExpr):
            return
        self._field_stores.setdefault(target.obj.name, set()).add(target.member)

    def _constructed_field_kind(self, e):
        """What `e.obj`'s construction put in `e.member`, or None.

        The second evidence source for a FIELD, and the one that is about the
        call site: a declaration says what a field's TYPE is, and a
        construction says what the VALUE in the slot is, and for the ordinary
        unannotated class only the second is stated anywhere.

        Unanimity or nothing, on the same rule `own_shape_kind` and
        `struct_field_kind` use and for the same reason: this map is
        flow-insensitive, so every construction of the name in this function is
        a statement about the same slot and two that disagree leave it
        undecided. One construction, one field, one kind — and the argument's
        own kind has to be EVIDENCE, not a fallback, which is why a bare name
        is asked of `own_shape_kind` and a call result is refused by
        `_own_shape_of`'s filter: `Point(a, b)` where `a` and `b` are this
        function's unannotated parameters says nothing about anything, and
        claiming otherwise is how a field would end up printed as a number."""
        obj = e.obj
        if not isinstance(obj, F.IdentExpr):
            return None
        if e.member in self._field_stores.get(obj.name, ()):
            return None
        calls = self._ctor_calls.get(obj.name)
        if not calls:
            return None
        kinds = set()
        for struct_name, call in calls.values():
            value = self._ctor_field_value(struct_name, call, e.member)
            if value is None:
                return None
            if isinstance(value, F.IdentExpr) and \
                    self.own_shape_kind(value.name) is None:
                return None
            kind = self.kind_of(value)
            if kind is None:
                return None
            kinds.add(kind)
        return kinds.pop() if len(kinds) == 1 else None

    def _unpacked_element_kind(self, value, kind, own):
        """`(kind, own)` for ONE ELEMENT of `value`, for a tuple target.

        `a, b, c = t` binds three names and each holds ONE element of `t`, not
        `t` itself, so the kinds this returns are the ELEMENT's. Without it the
        statement's own scan bound every name to the container's kind, and a
        container kind is not one of the two kinds a value can print as — so
        the ordinary shape was refused on both architectures:

            t = (1, 2, 3)
            a, b, c = t
            print(a)   # -> print() cannot tell whether IdentExpr is a string
                       #    or a number on the formal arm64/x86-64 path

        which is a sentence false about the source: the source says `a` holds an
        integer, and says it twice (the tuple literal's elements, and the fact
        that an unpack binds an element at all). The refusal was the whole
        observable effect here because a container kind is refused rather than
        guessed — `print(a)` cannot answer "is this a `%s` or a `%lld`" from
        `list:int`.

        A container LITERAL is asked for its elements' kinds directly rather than
        through its own `list_kind`, because `_kind_of_simple` — which
        `kind_of`'s container arm uses — classifies a LITERAL and nothing else,
        so `e, f = f, e` (a tuple of two NAMES, the swap) has an element kind
        its own container kind cannot carry and narrowed to `list` with no
        element at all. Reading the elements through `kind_of` is what makes the
        swap work, and it is the same reader `subscript_element_kind`'s callers
        use for `t[0]`.

        Only a LIST-kind value is narrowed, and the `is_list_kind` gate is what
        keeps the two shapes apart: `subscript_element_kind` deliberately maps
        `str` to an integer, because `s[0]` is a BYTE on this path
        (`subscript_element_kind`'s own docstring), and `a, b = "xy"` binds two
        one-character STRINGS. So the string arm is not narrowed at all — it
        keeps the container kind, which is wrong in the same way it was and no
        more so, rather than right for a reason this file does not have.

        `own` follows the element for the same reason `kind` does: the evidence
        is the same statement, one level down, and an own-shape claim about the
        container is not a claim about an element of it. This matters because
        `own_shape_kind` is the answer both backends' subscript/slice/membership
        choke points ask before treating a name as a container (`a[0]` after an
        unpack of a list of ints must read an integer, not a blob).
        """
        elem = None
        if isinstance(value, (F.TupleExpr, F.ListExpr)):
            kinds = {self.kind_of(el) for el in (value.elements or [])}
            kinds.discard(None)
            elem = kinds.pop() if len(kinds) == 1 else None
        else:
            # `k, v = d` binds two KEYS — CPython unpacks a mapping's keys and
            # nothing else — so the element kind here is the dict's KEY kind,
            # read by the same reader a `for k in d` uses
            # (`_iterable_dict_key_kind`, whose own docstring carries the
            # measurement: before it existed a dict walk's target classified as
            # an integer and `print(k)` printed an ADDRESS). It answers None for
            # anything that is not a dict with a stated initializer, which is
            # what makes it its own gate — asking `is_dict_value` first is
            # wrong, and measurably so: that reader works from `_dict_names`,
            # which a plain `d = {…}` ASSIGNMENT never reaches, so the arm
            # below it never ran and `len(k)` still said "classified as 'int'".
            elem = self._iterable_dict_key_kind(value)
            if elem is None and is_list_kind(kind or ""):
                elem = list_elem_kind(kind)
        if elem is None or elem == kind:
            return kind, own
        return elem, elem

    def _scan(self, stmts) -> None:
        for s in stmts or []:
            if isinstance(s, F.AssignStmt):
                # `d: String = x` is an `AssignStmt` with a `type_ann` and not a
                # `VarDecl`, so the declared-type reader has to be asked here as
                # well — see `_kind_with_ann`, whose docstring carries the
                # measurement of what happens when only one of the two arms asks.
                kind, own = self._kind_with_ann(s.value,
                                                getattr(s, "type_ann", None))
                if isinstance(s.target, (F.TupleExpr, F.ListExpr)):
                    # A TUPLE TARGET binds one element per name, and that is the
                    # same fact `_iterable_kind` states for a `for` over the
                    # same container — so it is the same reader.
                    kind, own = self._unpacked_element_kind(s.value, kind, own)
                self._bind_target(s.target, kind, own=own)
                self._note_construction(s.target, s.value)
                self._note_dict_init(s.target, s.value)
                self._note_field_stores(s.target)
                self._note_no_value_call(s.target, s.value)
                # The `VarDecl` arm gets these from `_bind_value`; this arm
                # binds the TARGET rather than a name, so it asks the two axis
                # readers itself, and it asks about the VALUE only — which is
                # `_bind_value`'s rule and the reason the `type_ann` this arm
                # also holds is not one of the arguments.
                self._note_spelling_axis(s.target, s.value)
            elif isinstance(s, F.VarDecl):
                self._bind_value(s.name, s.value,
                                 ann=getattr(s, "type_ann", None))
                self._note_construction(s.name, s.value)
                self._note_dict_init(s.name, s.value)
                self._note_field_stores(s.name)
                self._note_no_value_call(s.name, s.value)
            elif isinstance(s, F.AugAssignStmt):
                # `x += e` leaves x holding what it held; an unknown x stays
                # unknown rather than being called an int by the operator.
                self._bind_target(s.target, self.locals.get(
                    s.target.name if isinstance(s.target, F.IdentExpr) else ""))
                self._note_construction(s.target, s.value)
                self._note_dict_init(s.target, s.value)
                self._note_field_stores(s.target)
                self._note_no_value_call(s.target, s.value)
            elif isinstance(s, F.MultiAssignStmt):
                vkind = self._own_shape_of(s.value)
                for t in s.targets:
                    self._bind_target(t, self.kind_of(s.value), own=vkind)
                # One value for every target, so it is not a construction of
                # any one of them in the sense the field evidence needs; the
                # tombstone is what says so.
                for t in s.targets:
                    self._note_construction(t, s.value)
                    self._note_dict_init(t, s.value)
                    self._note_field_stores(t)
                    self._note_no_value_call(t, s.value)
            elif isinstance(s, F.ReturnStmt):
                self._returns.add(self.kind_of(s.value))
                # The dict half of the same statement. Recorded beside the kind
                # rather than derived from it, because the kind cannot say it:
                # a `return {"a": 1}` and a `return [1]` are the same kind here
                # and opposite answers to `d["a"]`.
                self._returns_dict.add(bool(self.is_dict_value(s.value)))
            elif isinstance(s, F.IfStmt):
                self._scan(s.then_body)
                for _c, body in (s.elifs or []):
                    self._scan(body)
                self._scan(s.else_body)
            elif isinstance(s, F.WhileStmt):
                self._scan(s.body)
                self._scan(s.else_body)
            elif isinstance(s, F.ForStmt):
                self._bind_for_target(s.target, self._iterable_kind(s.iterable),
                                      own=self._iterable_own_shape(s.iterable))
                self._scan(s.body)
                self._scan(s.else_body)
            elif isinstance(s, F.WithStmt):
                # A `with` HAS no `else_body` — `fire_compiler.WithStmt`
                # carries `items`, `body` and `is_async` and nothing else —
                # so scanning one was an `AttributeError` out of this walk,
                # reached by every function with a `with` in it. It was
                # introduced by `work/formal3-8-r2` together with a second
                # `ForStmt`/`WithStmt` pair, the earlier of the two: the two
                # edits interleaved in a merge and the result was one arm
                # reading a field that does not exist plus a duplicate of
                # itself and of its neighbour.
                #
                # The `own=` argument is the part of that branch's change
                # that is a real improvement and it is kept: the alias is
                # bound to the context expression's VALUE, so an own shape
                # read off that expression is the alias's own shape rather
                # than a guess from the name. The unreachable duplicate arms
                # are gone rather than left for the next reader to find.
                for it in (s.items or []):
                    if getattr(it, "alias", None) is not None:
                        self._bind(str(it.alias), self.kind_of(it.expr),
                                   own=self._own_shape_of(it.expr))
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
        """What a `for`/`in` binds from `iterable` — ONE ELEMENT of it.

        A container literal knows its own element kind; `range` yields integers;
        anything else is a blob whose elements this path treats as words
        (types.function_var_types says the same about loop variables). Never the
        container's own kind; `_iterable_own_shape` carries the measurement of
        what that cost."""
        return self._iterable_own_shape(iterable) or INT_KIND

    def _iterable_own_shape(self, iterable):
        """`_iterable_kind` without its final fallback, or None.

        The kind of the name a `for` (or a comprehension generator) over
        `iterable` BINDS — which is one ELEMENT of it, and never the container.

        **It used to answer the container's kind, and that was a wrong ANSWER on
        both architectures, not a missing refusal.** `["p", "", "q"]` is
        `list:str`, so the loop variable was classified `list:str` and every
        reader of a container took it at its word:

          * `if x:` → `truthy_lowering`'s `TRUTHY_FROM_BLOB_FIELD`, which is one
            load from offset 0. For a `char *` that load reads the eight bytes
            of `__TEXT,__text` that FOLLOW the terminating NUL, so whether the
            empty string came out truthy depended on which other string the
            linker happened to intern next to it. Measured on both machines,
            `for x in ["p", "", "q"]: if x: c = c + 1` returned 3 where CPython
            returns 2, and a two-element `["p", ""]` with an `else` returned 101
            — which is right only because the two strings happened to land
            adjacent to their own NULs;
          * `len(x)` → the same load, so it returned the low half of the
            address's own neighbourhood: 2013266032 (0x78000070, which is `p\0`
            and the first three bytes of the next interned string) for `"p"`.

        One element is what the target holds, so the element kind is what is
        returned, and `subscript_element_kind` is what already turns a container
        kind into an element kind for `x[i]`. The nested arm is
        `_kind_of_nested_elements` rather than `_kind_of_elements` because
        `for row in [[1, 2], [3, 4]]` is ordinary and its target IS a blob:
        without the arm the target kind would fall to the word default and
        `len(row)` — which works today and which the corpus uses — would start
        refusing.

        **A NAME whose kind carries an ELEMENT is the other shape, and it is the
        one a returned blob needs**: `for x in names: len(x)` over
        `names = listdir(p)` — `-> List[String]`, so the name's kind is
        `list:str` — refused with "an integer has no length" about a `char *`,
        because nothing read the element off the one place that states it. The
        answer is the element kind, and it is evidence for the same reason the
        literal arms are: the annotation said what the loop yields.

        The fallback is a word, and a word is not a claim that the source says
        "integer": `for row in rows: row[0]` over a parameter is the ordinary
        way to walk a list of lists and `_iterable_kind` answers INT_KIND for it
        because there is nothing else to answer. So the fallback is kept out of
        `own_shape` (this function returns None for it), which is what
        `own_shape_kind` reads; see that method for the three correct programs
        that depend on it.

        That direction is the conservative one and it is the measured one: it
        stays None for a name whose kind is the BARE list prefix, which is every
        container this path cannot give an element type to (a parameter
        annotated `List`, a nested container, a blob whose initializer claimed
        nothing), so `for row in rows: row[0]` over an unannotated parameter
        keeps working.
        """
        if isinstance(iterable, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            return _kind_of_nested_elements(iterable.elements)
        if isinstance(iterable, F.Comprehension):
            return _pair_value_kind(iterable.element)
        if isinstance(iterable, F.CallExpr) and _flat_callee(iterable) == "range":
            return INT_KIND
        keyed = self._iterable_dict_key_kind(iterable)
        if keyed is not None:
            return keyed
        if isinstance(iterable, F.IdentExpr):
            kind = self.name_kind(iterable.name)
            if is_list_kind(kind or ""):
                return list_elem_kind(kind)
        return None

    def _iterable_dict_key_kind(self, iterable):
        """The kind of the KEYS a walk over the dict `iterable` yields, or None.

        A dict is a pair blob, so what a `for k in d` binds is pair `i`'s KEY —
        never its value — and the key is what the walk addresses
        (`walk_stride`). This is the kind half of that; the stride half is the
        emitters'. Measured before this arm existed, on both architectures: for
        `d = {"ab": 1, "cde": 2}`, `print(k)` printed `4329047400` where
        CPython prints `ab` (a loop target classified as an integer is a
        `char *` formatted as a word, which is a plausible number rather than a
        fault), and `len(k)` was REFUSED as "an integer has no length" about a
        string the source plainly wrote.

        The same evidence `dict_literal_key_value_kind` insists on, and for the
        same reason: only the INITIALIZER states which words were written, so a
        dict literal answers for itself and a name answers through the
        `_dict_inits` statement that bound it. Every key the literal wrote is
        walked, so unanimity is over all of them and a mixed table claims
        nothing — the conservative direction, and the one the word fallback
        already took. A dict COMPREHENSION has no initializer to ask
        (`_iterable_own_shape` above answers it its own way), and neither has a
        dict that arrives from a call or a `Dict[…]` parameter, so those keep
        the fallback.
        """
        if is_dict_expr(iterable):
            return dict_literal_key_kind(iterable)
        if isinstance(iterable, F.IdentExpr):
            # `_dict_inits` and not `is_dict_value`: the latter reads
            # `_dict_names`, which a plain `d = {…}` ASSIGNMENT never reaches
            # (`_bind_dictness` is called from `_bind_value`, the `VarDecl`
            # arm), and what this needs is the INITIALIZER rather than the
            # dict-ness — the keys are what states their kind. A name with no
            # literal initializer answers None either way.
            return dict_literal_key_kind(self._dict_inits.get(iterable.name))
        return None

    def _element_kind_in_flow(self, elems):
        """The element kind of a container literal, resolving NAME elements.

        The instance method `_kind_of_elements` needs, and the reason it exists
        separately is the recursion: `kind_of` asks this, and this asks
        `name_kind`, so a literal that mentions a name bound FROM a literal of
        the same shape has to be cut off rather than followed. `_resolving` is
        that cut-off, and an element that is being resolved contributes nothing
        — which is the conservative direction, the same one `_kind_of_elements`
        already takes for an element it cannot classify.

        `_list_literal_elem_kind` and not `_kind_of_elements`, so a literal of
        literals answers with its ELEMENT's element kind: `rows = [[1, 2],
        [3, 4]]` is `list:list:int`, which is what makes `rows[0]`'s own kind a
        blob and `len(rows[0])` a count-field read. With the flat reader `rows`
        was a bare `list`, `subscript_element_kind` answered None, and the name
        the subscript was bound to fell to "a word is an integer"; measured on
        both architectures before the change (the deleted
        `FORMAL_len_of_a_subscript_of_a_list_of_lists_is_an_int.md`). That
        reader's own docstring carries why the flat answer is kept as its
        fallback — an element kind nothing here has seen before must not cost a
        program the claim it already had. The `_resolving` cut-off keeps the
        same shape here: a nested arm that resolves a name can ask for the
        name's kind, which is what the flat one already did.
        """
        if self._resolving:
            return _list_literal_elem_kind(elems)
        self._resolving = True
        try:
            return _list_literal_elem_kind(elems, self._name_kind_not_in_flight)
        finally:
            self._resolving = False

    def _name_kind_not_in_flight(self, name):
        """`name_kind` for a name read WHILE a container literal is being typed.

        A name this function's own statements have bound to two different kinds
        is undecidable, and `name_kind` already answers None for it — so the
        only thing this adds is the `_conflicts` check for the case where a name
        is bound to a list of UNKNOWN element and to something else, and
        answering a kind from the other binding would claim an element type the
        container does not have.
        """
        if name in self._conflicts:
            return None
        return self.name_kind(name)

    def _return_kind(self, fn) -> str | None:
        ann = getattr(fn, "return_type", None)
        if ann in self._int_names:
            return INT_KIND
        if ann in self._string_names:
            return STR_KIND
        return None

    def comprehension_generator_scopes(self, comp) -> list:
        """The names a comprehension's generator targets bind, per level.

        `scopes[i]` is what a site INSIDE generator `i` of `comp` sees: every
        name the generators `0 … i` bound, with the kind each one's own
        iterable says. `scopes[i-1]` — not `scopes[i]` — is therefore what
        generator `i`'s OWN ITERABLE sees, which is Python's rule and the reason
        the emitters push the level's scope just after the target store rather
        than on entry (see `formal/arm64_codegen.py::_emit_compr_gen`).

        **An overlay and not a `_bind` into `locals`, and the difference is
        SCOPE.** A comprehension is its own scope in Python 3, so `var x = 5`
        beside `[x for x in ["a", "b"]]` is two bindings of one name that do not
        meet, and a `_bind` would file them as a conflict — `locals[x] = None`,
        a word — which costs the OUTER `x` an answer it had and buys the
        comprehension's nothing. Worse in the other direction: a `_bind` makes
        the comprehension's target visible to every site in the function, so
        `printf("%s", x)` after a comprehension that binds `x` and nothing else
        emits instead of refusing a read CPython answers with `NameError`.

        So this is consulted only from inside the comprehension, and only for a
        bare NAME (a generator target is a name or a tuple of names, and a
        tuple target's per-element kind is one level deeper than the iterable's
        — see `_bind_target`, which has the same limit on the `for` statement).
        Nothing else changes: `own_shape_kind` deliberately does NOT read this,
        because it answers "did a STATEMENT OF THIS FUNCTION bind this name to
        a shape of its own" and a comprehension's target is bound by no
        statement of the function.

        The kind is `_iterable_own_shape`, never `_iterable_kind`, so an
        iterable this cannot describe claims nothing and the name falls through
        to the function's own map — which is what happened to every comprehension
        target before this existed, and is why a comprehension over a PARAMETER
        behaves exactly as it always has.
        """
        scopes: list = []
        bound: dict = {}
        conflicted: set = set()
        for gen in (getattr(comp, "generators", None) or []):
            own = self._iterable_own_shape(getattr(gen, "iterable", None))
            if own is not None:
                for nm in _comprehension_target_names(
                        getattr(gen, "target", None)):
                    if nm in conflicted:
                        continue
                    if bound.get(nm, own) != own:
                        # Two generators of one comprehension, one name, two
                        # kinds: the same unanimity rule `locals` follows, and
                        # for the same reason (the map is flow-insensitive, so
                        # two statements that disagree say nothing).
                        conflicted.add(nm)
                        bound.pop(nm, None)
                        continue
                    bound[nm] = own
            scopes.append(dict(bound))
        return scopes



    # ── querying ───────────────────────────────────────────────────────

    # The literal shapes that are DEFINITELY not a bool, and the ones that are
    # definitely not `None`. Both are asked by the axis readers below and both
    # exist for one reason: an axis that can only ever record `True` cannot
    # detect that two statements DISAGREE, and `_bind_spelling`'s unanimity rule
    # is what makes `b = True; b = 5; print(b)` write `5` rather than the first
    # binding's `True` (measured before this, on both architectures: it wrote
    # `True`). `_bind_dictness` records `False` for the same reason. A literal
    # is the one shape whose other-ness is a FACT rather than an inference,
    # which is why these two tuples hold literals and nothing else — an
    # arithmetic expression or a call claims nothing either way.
    _NOT_A_BOOL = (F.IntLiteral, F.FloatLiteral, F.StringLiteral,
                   F.ListExpr, F.TupleExpr, F.DictExpr, F.SetExpr)
    _NOT_NONE = (F.IntLiteral, F.FloatLiteral, F.StringLiteral, F.BoolLiteral,
                 F.ListExpr, F.TupleExpr, F.DictExpr, F.SetExpr)

    def is_bool_value(self, e):
        """True when `e` is a BOOL by this function's source, else False/None.

        `is_dict_value`'s shape for the BOOL axis, and it exists for the same
        reason: **a `Bool` has no kind of its own on this path.**
        `declared_type_kind` maps a `Bool` annotation to `INT_KIND` and
        `_kind_of_simple` maps a `BoolLiteral` to `INT_KIND`, which is RIGHT for
        every arithmetic site, every `len` and every comparison — a bool is a
        word holding 0 or 1 here. It is wrong for exactly one thing, and that
        thing is what CPython prints: `True`/`False` where `is_number_kind` says
        "%lld", so `print(flag)`, `print(x == y)` and `print(not x)` printed
        `1`, `0` and `0` on both architectures.

        The evidence, in the order it is used:

          * `bool_valued_shape` — the three shapes that ARE bools whatever any
            declaration says: a `BoolLiteral`, a comparison (`_COMPARISON_OPS`,
            which includes `is`/`in`), and `not`. No table and no flow needed.
          * a NAME this function bound — from `_bool_of`, under the same
            unanimity rule as `locals` and `_dict_names`: two statements that
            disagree leave the name out entirely, so the caller keeps what it
            did before. **Which needs a False to be reachable at all** — see
            `_NOT_A_BOOL`, without which this axis could never disagree with
            itself and `b = True` then `b = 5` kept the first answer;
          * a LITERAL of another kind — False, and the reader above is why that
            is a fact rather than an inference;
          * a CALL to a function of this module declared `-> Bool` — the
            `callee_is_bool` hook, which is `_callee_is_dict`'s on this axis and
            for the same reason (the evidence is about another function, so it
            is the emitter's table and its recursion guard).
          * a PARAMETER or a bracketed parameter annotated `Bool` — recorded in
            `__init__` from the same loop that seeds `locals`, because a
            signature binds a name that no statement in the body binds.

        None for everything else, and the None is the permissive direction: a
        word this build cannot say is a bool about keeps being printed the way
        this path has always printed it.

        Deliberately NOT asked about a `MemberExpr` or a `CallExpr`. Both would
        need evidence this class does not hold — a field's declared type is the
        `declared_kind` hook's, and a callee's declared return type belongs to
        the EMITTER's function table (`formal/build.py` lifts `Box.put` to one
        flat name, and only the emitter knows the lifting) — so the emitter's
        `is_bool` hook asks those two itself and this answers the rest.
        """
        if e is None:
            return None
        if bool_valued_shape(e):
            return True
        if isinstance(e, self._NOT_A_BOOL):
            return False
        if isinstance(e, F.IdentExpr):
            if e.name in self._bool_conflicts:
                return None
            return self._bool_of.get(e.name)
        if isinstance(e, F.CallExpr):
            # A `-> Bool` CALLEE, which is the `callee_is_dict` hook read on this
            # axis and for the same reason: the evidence is about ANOTHER
            # function, so it is the emitter's table and its recursion guard.
            # Only the DECLARED return type is read — a callee that returns
            # `True` from every `return` without saying `-> Bool` claims
            # nothing, which is the conservative direction and keeps a new
            # `return_*` axis out of this class for one spelling of one fact.
            callee = _flat_callee(e) or subscript_callee_name(e)
            if callee is None:
                return None
            return self._callee_is_bool(callee)
        return None

    def is_none_value(self, e):
        """True when `e` is the `None` singleton, False when it is a value, and
        None when this function's source does not say.

        The third of the three axes `kind_of` cannot carry, and the one with the
        least evidence behind it, which is why it is also the one with the
        narrowest reader: **`None` has no representation on this path at all** —
        a formal value is one 64-bit word and this is the absence of one — so
        the ONLY way to render it correctly is to know at BUILD time that the
        operand is `None` and write those four characters into the format string
        (`print_constant_text`). A word that MIGHT be `None` cannot be printed
        at all, and that is a refusal this path states rather than a number.

        The evidence: the `None` expression itself (`is_none_expression`, which
        knows both spellings the parser produces), a NAME every statement of
        this function binds to one, from `_none_of` under the unanimity rule —
        which needs a False to be reachable at all, so a literal of another kind
        answers False (`_NOT_NONE`) and `n = None` then `n = 5` leaves the name
        out instead of keeping the first binding — and a NAME every statement
        binds to something else, which answers False for the same reason.
        `n = None; print(n)` printed `0` on both architectures before this
        existed; `n = None` then `n = 5` then `print(n)` claims nothing, which
        is the rule that keeps the first fix from being a wrong one.
        """
        if e is None:
            return None
        if is_none_expression(e):
            return True
        if isinstance(e, self._NOT_NONE):
            return False
        if isinstance(e, F.IdentExpr):
            if e.name in self._none_conflicts:
                return None
            return self._none_of.get(e.name)
        return None

    def is_bytes_value(self, e):
        """True when `e` is a `bytes`, False when it is a `str`, None when this
        function's source does not say.

        The FOURTH axis with no KIND of its own, and the only one that is not
        about spelling: a `bytes` literal classifies as `STR_KIND`
        (`_kind_of_simple`), which is right for every kind-consuming question —
        `len(b)`, `b == b"ab"` and `b"a" in b` all agree with CPython, because a
        `bytes` and a `str` of the same characters measure and compare the same.
        What CPython does NOT agree about is the one question that is not a
        question about a kind: `print` writes `repr(b)`, which is `b'ab'` where
        this path used to write `ab` (measured, both architectures, for a NAME as
        well as for the literal — `b = b"ab"; print(b)`).

        So the reader is asked by `print` alone, which is stated here so a second
        caller is a decision rather than an accident. A NAME's answer comes from
        `_bytes_of` under the same unanimity rule as the other three axes, so
        `b = b"ab"` then `b = "ab"` claims nothing and the name prints as the
        `str` it is.

        Deliberately NOT asked about a `MemberExpr` or a `CallExpr`, for the
        reasons `is_bool_value` gives: both need the emitter's tables, and a
        `bytes` that arrives from a kernel call is `FOREIGN_BYTES_KIND` — where
        printing the bare text is CORRECT, because a `char *` the kernel
        supplied is not a `bytes` object and CPython would not print a `repr()`
        of it either (`os.listdir(p)[0]` is a `str` there, per that kind's own
        comment).
        """
        if e is None:
            return None
        if isinstance(e, F.StringLiteral):
            return bool(getattr(e, "is_bytes", False))
        if isinstance(e, F.IdentExpr):
            if e.name in self._bytes_conflicts:
                return None
            return self._bytes_of.get(e.name)
        return None

    def is_dict_value(self, e):
        """True when `e` evaluates to a DICT, False when it is a container of
        some other kind, and None when this function's source does not say.

        THE QUESTION `kind_of` CANNOT ASK**, and the reason is that on this path
        a dict and a list are the same word: `_emit_dict` lays a dict out as
        `[count][k0][v0][k1][v1]…` and `_emit_list` as `[count][e0][e1]…`, both
        a count header followed by eight-byte slots, and `kind_of` answers
        `list_kind(...)` for both. So the kind of a value cannot say which one
        a subscript with a STRING index means, and the emitter's own
        `_is_dict_subscript` had to keep a second, flow-sensitive map
        (`_dict_vars`) beside the kind — a second answer to a question the
        model already had most of the evidence for and nobody had asked it of.

        The evidence, in the order it is used:

          * `is_dict_expr` — a dict literal or a dict comprehension. The one
            shape both spellings agree on.
          * a NAME this function bound — from `_dict_names`, under the same
            unanimity rule as `locals`: two statements that disagree leave the
            name out entirely, so the caller keeps what it did before.
          * a CALL to a function of this module — the `callee_is_dict` hook,
            which is the backend's `_callee_kind` read on this axis, so a
            recursion guard and a memo are already in place there.
          * a PARAMETER annotated `Dict[…]` — its own annotation, which is the
            same "the declaration is a fact about the value" rule
            `declared_kind` already follows for the kind axis.

        None for everything else, deliberately: an unstated shape is not a "not
        a dict", and treating it as one is how `d["a"]` reached the sequence
        path in the first place.
        """
        if e is None:
            return None
        if is_dict_expr(e):
            return True
        if isinstance(e, F.IdentExpr):
            if e.name in self._dict_conflicts:
                return None
            return self._dict_names.get(e.name)
        if isinstance(e, F.MemberExpr):
            key = self._slot_key(e)
            if key is not None and key in self._dict_conflicts:
                return None
            if key is not None and key in self._dict_names:
                return self._dict_names[key]
            # Nothing this function bound says, so the DECLARATION is what is
            # left: `self.seen` is a frame slot, and its field's annotation is
            # the only statement anywhere about what the slot holds. Asked after
            # `_dict_names` and not instead of it, so a binding statement keeps
            # its precedence over a declaration — the same order
            # `declared_kind` is consulted in.
            answer = self._declared_is_dict(e)
            return None if answer is None else bool(answer)
        if isinstance(e, F.CallExpr):
            callee = _flat_callee(e) or subscript_callee_name(e)
            if callee is None:
                return None
            answer = self._callee_is_dict(callee)
            return None if answer is None else bool(answer)
        return None

    def dict_inits(self) -> dict:
        """`{name: DictExpr}` for the locals of this function whose EVERY
        binding is that same dict literal.

        The evidence a `**` spread through a LOCAL is un-spread with — see
        `_unspread_keyword_mappings`, whose option this is. The tombstone rule
        `_note_dict_init` already carries is exactly the doc's "only ever bound
        such a literal": a name bound to two different literals, or to anything
        that is not one, is recorded as `None` and is ABSENT from this answer, so
        the caller keeps its refusal. That makes the census's phrase and the
        lowering's decision the same question rather than two.

        A second reader of `_dict_inits`, beside `is_dict_value`. The two differ
        in what they need back: a subscript wants the dict-NESS of the name
        (`_dict_names`), which a call or an annotation can also answer, while a
        spread wants the ELEMENTS themselves, which only a literal in the source
        provides.
        """
        return {name: node for name, node in self._dict_inits.items()
                if node is not None}

    def appended_names(self) -> frozenset:
        """The names `xs.append(...)` is called on anywhere in this function.

        The append-capacity scan in each backend has its own richer map
        (`_scan_list_caps`, keyed by literal and by name), but this question is
        narrower and belongs to the KIND model: a list literal's element kind
        is evidence about the list only while nothing grows it, because
        `v = [1]; v.append([2])` has a `list:int` shape and an element that is
        itself a list. The subscript-evidence arm in
        `scalar_container_base_evidence` is the caller.

        Nested `def`/`lambda` bodies are not descended into, via
        `walk_stmt_trips` — their `append` is their own scope's, not this
        function's, and counting it would decline the evidence for a name it
        never grew.
        """
        if self._appended_names is None:
            out = set()
            for node, _trips in walk_stmt_trips(
                    getattr(self._fn, "body", None) or [], lambda _s: 1):
                if (isinstance(node, F.CallExpr)
                        and isinstance(node.func, F.MemberExpr)
                        and node.func.member == "append"
                        and isinstance(node.func.obj, F.IdentExpr)):
                    out.add(node.func.obj.name)
            self._appended_names = frozenset(out)
        return self._appended_names

    def own_shape_kind(self, name: str):
        """What a statement of THIS function bound `name` to, on the EVIDENCE
        of that statement alone — or None when no such statement says.

        **The question `name_kind` cannot answer, and the reason the container
        operations cannot treat `INT_KIND` as "not a container".** `INT_KIND` is
        this model's DEFAULT for a word, not a reading of the source: an
        unannotated parameter is seeded to it because a word arriving from a
        caller is a word, and `_value_kind` returns it for any expression it
        could not classify. So `name_kind("xs") == INT_KIND` holds for three
        quite different things, and only the first is an integer:

        | the source | `name_kind` | `own_shape_kind` |
        |---|---|---|
        | `a = 5` | `int` | `int` — the source SAYS so |
        | `ys = h.get()` | `int` (unclassified) | `None` — nothing said |
        | `for row in rows:` | `int` (unclassified) | `None` — nothing said |

        The second and third are the two shapes that make the default useless
        as evidence, and the third is the ordinary way to walk a list of lists:

            def walk(n, rows):            def first(rows):
                for row in rows:               var head = rows[0]
                    printf("%d", row[0])       return head[0]

        Measured, both architectures, before this question existed: all three
        built and answered correctly, so a refusal that reads the default as a
        claim refuses correct programs — and a wrong answer is worse than a
        refusal everywhere else in this backend.

        What counts as evidence is `_own_shape_of`, which is `kind_of` — the
        same classification the rest of the model uses, and the same
        fall-through chain: a literal, an arithmetic operation over classified
        operands, a comparison, a container literal, a `range` loop target.
        What does NOT count is any fallback: not `_value_kind`'s default, not
        `_iterable_kind`'s, not a call's (see `_own_shape_of` for why a call is
        the one expression whose kind carries no evidence at all), and not the
        nested-`def` binding. A name two statements of this function bind two
        ways is a conflict and claims nothing, for the same reason `name_kind`
        answers None for it.

        A MODULE GLOBAL is deliberately outside this, as it is outside
        `locals`: its binding is a statement of the MODULE, not of this
        function, and `name_kind` may classify it from its slot's initializer
        through `global_slot_kind`. That is the right question for it and this
        is not.

        Asked from both backends' single subscript/slice/membership/for-in
        choke point, so the two architectures cannot come to disagree about
        which bases are containers — which is the half of this that is a
        language question rather than a wording one.
        """
        if name in self._conflicts:
            return None
        kinds = self._own_shape.get(name)
        if not kinds or len(kinds) != 1:
            return None
        return next(iter(kinds))

    def name_kind(self, name: str):
        """What the local `name` holds, or None if this does not say."""
        if name in self._conflicts:
            return None
        kind = self.locals.get(name)
        if kind is not None:
            return kind
        # A MODULE GLOBAL this function does not bind. Its value's shape is
        # stated at module level, in the slot's own initializer, and a use site
        # has nothing else to go on — so without this a container global is an
        # unclassified word and `len(arr)` refuses a length the image has.
        # Measured, on the tree this landed on: `arr = [1,2,3]` at module level
        # with `len(arr)` in the body stopped being answerable the moment the
        # binding stopped being a body statement (a container global's store is
        # the slot's initializer, not a store — `module_body`), and the
        # refusal sent the reader to annotate a name the source had already
        # given a list to.
        gk = global_slot_kind(name)
        if gk is not None:
            return gk
        # A TYPE, read as a value. LAST, and the order is the guard rather than
        # an afterthought: a local (`Int = 7` — `a_local_named_like_a_type_
        # still_wins` in test_formal_run.py) and a module global of the same
        # spelling both answer first, so this cannot reintroduce the bug the
        # tag's placement was moved to fix. What it replaces is the absence: an
        # unbound type name classified as nothing, which is what made `len(bool)`
        # say the source does not say what its operand holds.
        return (TYPE_KIND if type_tag_for_name(name) is not None else None)

    def kind_of(self, e, scopes=()):
        """What `e` evaluates to, or None when the source does not say.

        `scopes` is the comprehension scope STACK (`ValueKinds`.
        `comprehension_generator_scopes`, outermost first) and is empty
        everywhere except on a site inside a comprehension. A bare name the
        innermost such scope binds is answered by that scope and by nothing
        else — see `scope_lookup` for why it does not fall through, and
        `comprehension_generator_scopes` for why the scopes exist rather than
        being a `_bind` into `locals`.
        """
        if scopes and isinstance(e, F.IdentExpr):
            found, scoped = scope_lookup(scopes, e.name)
            if found:
                return scoped
        k = _kind_of_simple(e)
        if k is not None or isinstance(e, (F.StringLiteral, F.IntLiteral,
                                           F.BoolLiteral, F.FloatLiteral)):
            return k
        if isinstance(e, F.IdentExpr):
            kind = self.name_kind(e.name)
            # A METHOD RECEIVER of a one-word struct is the struct's only
            # field, so its declaration — not the "a word is an integer"
            # default the parameter got above — is what says what it holds.
            # Asked only of a name the SIGNATURE bound: a name the body bound
            # is flow's business, and flow already recorded it.
            if (kind == INT_KIND and e.name in self._param_names
                    and e.name not in self._conflicts):
                declared = self._declared_kind(e)
                if declared is not None:
                    return declared
            return kind
        if isinstance(e, F.MemberExpr):
            # A FIELD READ. The declared type of the field is the better
            # answer than anything flow has: `h.x` is a load out of a frame
            # whose layout the declaration fixes, and a name flow happened to
            # bind to a list elsewhere in this function says nothing about
            # what slot 8k holds.  A `None` from the hook leaves the local-slot
            # lookup below exactly as it was.
            declared = self._declared_kind(e)
            if declared is not None:
                return declared
            # …and the CONSTRUCTION is the second source, for the case the
            # declaration cannot reach at all: an unannotated class states
            # nothing, and `struct_field_kind`'s own gate — a kind is a claim
            # about the VALUE in the slot, and `S()` leaves every slot at its
            # class-level default — is right about `S()` and wrong about a
            # frame this very function built with arguments.  Asked AFTER the
            # declaration, so a class that says both is decided by the
            # declaration, and a `None` from either leaves the lookup below
            # exactly as it was.
            constructed = self._constructed_field_kind(e)
            if constructed is not None:
                return constructed
            key = self._slot_key(e)
            return self.name_kind(key) if key is not None else None
        if isinstance(e, F.CallExpr) and isinstance(e.func, F.IdentExpr):
            # A CONSTRUCTOR of a one-word struct produces that struct's only
            # word, so `r = B(); len(r)` is answerable for the same reason
            # `len(self.<f>)` is: the receiver IS the field.  Asked before the
            # CallExpr arm below, which reaches its answer from the callee
            # NAME — and a type constructor's name says what it constructs, not
            # what the word it makes holds.
            declared = self._declared_kind(e)
            if declared is not None:
                return declared
        if isinstance(e, F.UnaryOp):
            if e.op in ("*", "**"):
                return None              # *args / **kwargs have no single kind
            return self.kind_of(e.operand)
        if isinstance(e, F.BinaryOp):
            if e.op in _COMPARISON_OPS or e.op in ("and", "or"):
                return INT_KIND          # a comparison or a bool is 0/1
            return _unify(self.kind_of(e.left), self.kind_of(e.right), e.op)
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
            # `self._element_kind_in_flow` and not `_kind_of_elements` bare, so a
            # literal whose elements are NAMES is classified from this function's
            # own bindings. Recursion-guarded, because `x = [x]` would otherwise
            # ask a name's kind while that name's kind is being computed.
            return list_kind(self._element_kind_in_flow(e.elements))
        if isinstance(e, F.SliceExpr):
            # A slice is a NEW BLOB holding the selected elements, so its kind
            # is the sliced expression's kind narrowed to its element kind —
            # and its element kind is the source's, so `xs[1:3]` over a list of
            # ints is a list of ints and nothing has to be re-derived.
            #
            # There was no arm here, so a slice classified as NOTHING, and that
            # is a refusal with two faces: `len(xs[1:3])` was refused for want of
            # a shape the construct has exactly, and `var ys = xs[1:3]` bound
            # `ys` to the "a word is an integer" default — which is the
            # `infer_expr` lead the slice bug doc recorded, since `_value_kind`
            # only keeps an unclassified value that `_is_container_literal`
            # recognises and a slice is not a literal.
            return list_kind(list_elem_kind(self.kind_of(e.obj)))
        if isinstance(e, F.DictExpr):
            # The VALUES, because that is what a subscript of a pair blob
            # yields — the same element the layout interleaves them in
            # (`_emit_dict`), read here by the one function every container
            # literal's element kind comes from.
            return list_kind(container_literal_elem_kind(e))
        if isinstance(e, F.Comprehension):
            # The element and the key are asked in this comprehension's OWN
            # generator scope, because that is where the names they mention are
            # bound — and `[k for k in d]`'s element is nothing but such a name.
            #
            # It was `_kind_of_simple`, which classifies a LITERAL and has no arm
            # for a name, so every comprehension whose element is its generator's
            # own target classified as the BARE `list`: no element kind at all,
            # and a later walk over the result fell back to the "a word is an
            # integer" default. Measured on both architectures,
            # `d = {"ab": 100, "cde": 200}; ks = [k for k in d]; for k in ks:
            # len(k)` was REFUSED — "len() of a value classified as 'int', and
            # an integer has no length" — about a string the source plainly
            # wrote, while `for k in d` over the SAME literal answers `2` then
            # `3`. Two walks over one dict disagreeing about what a key is, and
            # the generator scope already said `str` (`comprehension_generator_
            # scopes` below); the loss was here, on the way out.
            scopes = self.comprehension_generator_scopes(e)
            if e.kind == "dict":
                # `e.element` is the dict comprehension's KEY (`e.value` is the
                # value), so this is the same arm as the `DictExpr` above and not
                # the key/value unification a LIST comprehension does below.
                return list_kind(self.kind_of(e.element, scopes))
            return list_kind(self.kind_of(e.element, scopes))
        if isinstance(e, F.CallExpr):
            # A LOWERED `external_call["sym", RetType](…)`, asked FIRST and
            # before the deref arm, because its declared return type is the only
            # thing that says what the word in the return register holds and the
            # generic arms below cannot see it: `_flat_callee` finds no callee
            # NAME in a bracketed template and the extern default answers
            # `INT_KIND`.  A pointer return must NOT be that — see
            # `external_call_result_value_kind`, which carries the measurement
            # and answers a `char *` declaration POINTER_KIND.
            extern = external_call_result_value_kind(e)
            if extern is not None:
                return extern
            # A POINTER DEREFERENCE, asked FIRST: `p.value()` is a call whose
            # callee is a member and whose receiver is a pointer, so the arms
            # below (which read a callee NAME) cannot classify it and would
            # answer `None` — the unclassified word that made
            # `Int(p.value())` over a `Pointer[Float64]` read the exponent
            # field.  `None` for every other call leaves each arm below exactly
            # where it was.
            deref = self._deref_kind(e)
            if deref is not None:
                return deref
            callee = _flat_callee(e)
            # The empty-container constructor, in EITHER spelling — `List()` and
            # `List[Int]()` are the same construction and must be the same
            # answer, which is why this is asked of `subscript_callee_name(e)
            # or callee` rather than in either arm. Without it, `var a =
            # List[Int]()` bound `a` to the "a word is an integer" default and
            # every later `len(a)` was refused with "len() of a value classified
            # as 'int'" — a claim about the value kind that the CONSTRUCTOR in
            # the same line contradicts, and one the two spellings disagreed
            # about (the bracketed one reached `_flat_callee`'s None arm, the
            # bare one reached the type-constructor fallback).
            # `blob_constructor_lowering` and NOT `empty_blob_constructor`, so
            # this arm and the emitter's cannot answer differently: a
            # `capacity=` reservation produces the same empty blob the
            # zero-operand form does, and a local bound to one of those (`var d =
            # List[Int](capacity=4)`) was classified an integer while the emitter
            # emitted a blob for it — so `len(d)` was refused with "an integer
            # has no length" about a container the same line had just built.
            ctor = subscript_callee_name(e) or callee
            lowering = (blob_constructor_lowering(ctor, e.args, e.kwargs)
                        if ctor is not None else None)
            if lowering is not None:
                # The BYTE kind when the constructor builds a byte blob, and
                # this is the one place that decision is made for a value:
                # everything downstream — `len` off the count field, the
                # one-byte subscript, the stride a walk takes — reads the KIND
                # and not the callee's name. A `List()` and a `bytearray()`
                # are both `[count][element 0]…` and both answerable here, and
                # they are told apart here and nowhere else.
                if ctor in BYTE_BLOB_CTORS:
                    return byte_blob_kind()
                return LIST_PREFIX
            if callee is None:
                return None
            # A call that hands one of its arguments straight back keeps that
            # argument's PROVENANCE, which is a fact a declared `-> String`
            # cannot carry: `def ident(s: String) -> String: return s` called
            # on a kernel string is still a kernel string, and `len(y)` on the
            # result must be the same refusal the direct spelling gets rather
            # than a `strlen` answering in bytes. Measured wrong on both
            # architectures before this arm: `[héllo] chars=6`, exit 0.
            #
            # A spread before the position would shift which argument lands
            # there, so such a call is not answered here — the same refusal to
            # guess the kind tables make everywhere else.
            back = self._callee_returned_parameter(callee)
            if back is not None:
                args = list(e.args or ())
                spread = any(isinstance(a, F.UnaryOp) and a.op in ("*", "**")
                             for a in args[:back + 1])
                if not spread and back < len(args) \
                        and is_foreign_bytes_kind(self.kind_of(args[back])):
                    return FOREIGN_BYTES_KIND
            # A lowered string method, asked first: `m = s.strip()` binds `m`,
            # and if `m` came back as a word then the NEXT method call on it
            # would be refused for want of a kind and a correct program would
            # stop. The receiver's own kind is the condition, for the same
            # reason the backend guards the lowering on it.
            skind = self._string_method_kind(e)
            if skind is not None:
                return skind
            # A DEREFERENCE whose pointee is a DOUBLE: `p.value()` is one word,
            # and its kind is the pointee's, not a shape of the call.  Asked here
            # — after the string-method arm, before the "an extern returns a
            # word" default below — because that default would otherwise answer
            # `INT_KIND` for a load of a double and every consumer would then
            # treat the bit pattern as an integer.  `None` (the common case, and
            # every non-float pointee) leaves the default exactly where it was.
            pk = self._pointer_pointee_kind(e)
            if pk is not None:
                return pk
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
            # `p[i]` over a POINTER is a DEREFERENCE, and the same hook the
            # `p.value()` spelling asks answers it — the SUBSCRIPT half of the
            # load, and it cannot be left out: `subscript_base_lowering` reads
            # the same `POINTEE_WIDTHS`, so a `Pointer[Float64]` would load
            # through `p[i]` while `Int(p[i])` still bit-moved.  `None` for
            # every non-pointer base (a list, a dict, a string), so the
            # container reading below is reached exactly as before.
            pk = self._pointee_kind(e)
            if pk is not None:
                return pk
            if not isinstance(e.index, F.SliceExpr):
# A dict subscript is a KEY SCAN, and its answer is a claim
                # about ONE element word — a word that a store writes and
                # nothing else does. So the initializer this function ran is
                # asked whether it wrote the key, and that is a question a KIND
                # cannot answer: `{"a": [1]}` says the dict holds lists, and
                # `d["b"]` reads a slot nothing put a list into.
                # `dict_literal_key_value_kind` carries the gate and returns
                # None for every shape it cannot vouch for, so the fallback
                # below is reached exactly as before — and that fallback is
                # `subscript_element_kind`, not a bare `list_elem_kind`, so a
                # `char *` still answers INT (`s[0]` is a BYTE, which is what
                # makes `printf("%s", s[0])` a refusal rather than a SIGSEGV).
                keyed = self._dict_subscript_kind(e)
                if keyed is not None:
                    return keyed
                return subscript_element_kind(self.kind_of(e.obj))
        return None

    def _dict_subscript_kind(self, e):
        """What `e`'s dict subscript yields, when this body wrote the key.

        The `_dict_inits` lookup and nothing else: a base that is a NAME is the
        only shape whose initializer the scan can attribute to a binding, and a
        subscript of a subscript (`d["a"]["b"]`) or of a field
        (`self.d["a"]`) has no initializer in this map, so it falls through to
        the list reading rather than reaching for one. That is the conservative
        direction and it is the same refusal the shape got before.
        """
        obj = e.obj
        if not isinstance(obj, F.IdentExpr):
            return None
        return dict_literal_key_value_kind(self._dict_inits.get(obj.name), e.index)

    def _string_method_kind(self, call):
        """What a lowered or folded string method call yields, or None.

        None for a method the model does not lower or fold, for a bare name,
        and — the case that makes this a guard rather than a lookup — for a
        method whose receiver is not classified as a string. `x.value()` on a
        struct whose kind is unknown must stay unknown here, or the caller would
        bind `x`'s result to a string and format an integer as text.

        The receiver gate is what stops a folded method from being believed on
        a receiver it cannot be: a fold needs its receiver to be a LITERAL, and
        `"abc".upper()` is one while `s.upper()` is not — so on a name the
        answer is None and the name binds to an unclassified word, which is the
        conservative direction and the same one the five libc-backed methods
        already took.
        """
        func = call.func
        if not isinstance(func, F.MemberExpr):
            return None
        method = func.member
        if method not in POINTER_BOUNDED_METHODS \
                and method not in STRING_FOLDED_METHODS:
            return None
        if not string_method_yields_string(
                call, string_operand_is_string(self.kind_of(func.obj))):
            return None
        return string_method_result_kind(method)


_COMPARISON_OPS = ("<", ">", "<=", ">=", "==", "!=", "is", "is not", "in",
                   "not in")




def subscript_callee_name(call) -> str | None:
    """The bare name a SUBSCRIPT callee is applied to, or None.

    `List[Int]()` → `List`.  The counterpart to `_flat_callee`, which answers
    None for this shape on purpose (a bracket is not a dotted chain), so the two
    together cover every spelling a call's callee can have and neither
    re-derives the other's rule.

    PUBLIC, and asked from all three places that need it — `ValueKinds.kind_of`
    (what the call produces), and BOTH backends (whether it is the empty-
    container constructor) — because the two backends disagree about how much
    of a subscript callee they can flatten (`arm64_codegen._callee_symbol` has
    carried a `SubscriptExpr` arm for a long time and `x86_64_codegen`'s copy
    has not, which is a pre-existing x86-64 gap listed in
    `bugs/formal/FORMAL_wide_receiver_by_reference.md` §5.1).  Collapsing that gap is
    not this change's job, so the shared question is asked at the level both
    backends can answer: the BASE NAME, which is the whole of what the
    empty-container decision needs.
    """
    func = getattr(call, "func", None)
    if not isinstance(call, F.CallExpr) or not isinstance(func, F.SubscriptExpr):
        return None
    return func.obj.name if isinstance(func.obj, F.IdentExpr) else None


def _param_list(fn):
    return list(getattr(fn, "params", None) or [])


def bracket_value_params(fn):
    """`(name, annotation)` for every BRACKET parameter that DECLARES a type.

    A bracket parameter is a different list from `params`, and this is the one
    reader of it: `def f[T: AnyType, keys: List[T]](base: Int)` has `keys` in
    the bracket block alone, so `_param_list` cannot see it and used to make
    every reader in this file treat a read of it as a read of an unknown name.

    Every bracket parameter with an annotation is returned, TYPE parameters
    included -- see the note at the call site. The pair is `(name, annotation)`
    with the annotation's TEXT, which is what `declared_type_kind` reduces, and
    an empty annotation yields no pair, so a bracket parameter written without
    one is exactly as invisible here as it was before.
    """
    out = []
    for name in (getattr(fn, "comptime_params", None) or []):
        if not isinstance(name, str) or not name:
            continue
        ann = (getattr(fn, "comptime_param_annotations", None) or {}).get(name)
        if isinstance(ann, str) and ann.strip():
            out.append((name, ann))
    return out




# ── The kind of a PARAMETER, from the call sites rather than from an annotation
#
# `ValueKinds` seeds an unannotated parameter as a word, and a word is an integer
# here (see the note on kinds). That default is right for every kind on this path
# EXCEPT one, and the exception is a wrong ANSWER rather than a refusal:
#
#     def f(s):
#         if s:            # `truthy_lowering`'s third row: the word itself
#         return 1         # the empty string is a NON-NULL pointer, so this
#     return 0             # is TRUE
#     f("")               # -> 1, where CPython says 0
#
# Measured on both architectures, and the same program with `s: String`
# annotated answers 0. The annotation is the only thing that closes it today,
# which is the gap `ValueKinds`' own docstring records for `print` ("A `char *`
# reaching print through an unannotated parameter is the remaining gap, and it is
# the gap the annotation exists to close").
#
# So: the call site's argument kind, propagated into the callee. This is the part
# of that which is decidable from the argument's OWN SHAPE — a string literal, or
# a call to a function whose declared return type is a string — and the rule is
# UNANIMITY over every call site of the name in the image, because a parameter
# that is a string at one call site and something else at another is a word and
# nothing else is an answer. A call site whose argument shape says nothing claims
# nothing, which is the permissive direction the rest of this file's kind tables
# take wherever the alternative is a refusal on the majority of a corpus.
#
# What it deliberately does NOT read, and why each is a decision rather than an
# omission:
#
#   * the CALLER's `ValueKinds`, so `f(some_local)` where `some_local` holds a
#     string is still unclassified. Reading it would mean building a ValueKinds
#     per caller from inside the callee's, which is the recursion `func_kind`
#     already guards with a depth limit — and a kind that depends on which
#     function the emitter reached first is a worse answer than no answer, since
#     it decides whether `printf("%s", s)` formats a pointer or bytes;
#   * a SPECIALIZED call, `f[a](x)`, whose brackets shift every position by the
#     comptime parameters. Skipping the whole call is the conservative reading
#     and costs only the generics;
#   * a call with KEYWORDS, whose positions are not the positional order. A call
#     that is keywords only is read by name; a call that mixes them binds the
#     positionals to parameters this function does not enumerate, so it claims
#     nothing at all;
#   * `*args` / `**kwargs` at the call site, for the same reason.


def _parameter_argument_shape(arg, rets=None):
    """The KIND an argument's own SHAPE states, or None when it states none.

    Two rows and they are the same evidence: what the caller WROTE at this call
    site. A string literal is a `char *`; a container literal is a `[count][…]`
    blob whose count field is its first word; and a call to a function whose
    declared (or inferred) result is one of those is whatever that function
    produces. `bytes` is excluded from the string row exactly as it was before
    this function grew a second one — a bytes literal is not a `char *` this
    path can `strlen`.

    **The container row is the one `len()` of a LIST PARAMETER needs, and it is
    here rather than in the `len` reader for the reason
    `bugs/formal/FORMAL_len_of_a_list_parameter_is_refused_though_the_same_parameter_
    subscripts.md` gives: the parameter is a blob, `xs[i]` on it already lowers
    through the blob path (`subscript_base_lowering`'s own answer for a base no
    declaration makes a pointer), and only `len` — the one reader that insists
    on a KIND — disagreed with it, refusing with "len() of a value classified
    as 'int'" about a container the same function subscripts.** Adding a second
    reader for `len` would have left the disagreement in place for the next
    reader; putting the evidence in the kind table settles it once, and every
    reader benefits: the subscript's element kind, truthiness (a blob is empty
    when its count is zero, which is CPython's answer and which the word's own
    non-zeroness got wrong for an empty list), and `printf`'s operand reader.

    The ELEMENT kind comes from `_list_literal_elem_kind`, so `[1, 2, 3, 4]`
    gives `list:int` rather than a bare `list` — which is what lets `xs[i]` be
    an integer and not merely a blob. A COMPREHENSION is the one container row
    that claims the blob and not the elements, and its own comment gives why.

    None is the answer for everything else, and it is what keeps the table's
    unanimity rule meaningful: a call site that says nothing is a claim of
    nothing, so one opaque argument withdraws the whole parameter's kind rather
    than leaving it to be guessed at from the others.
    """
    if isinstance(arg, F.StringLiteral) and not getattr(arg, "is_bytes", 0):
        return STR_KIND
    if isinstance(arg, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        return list_kind(_list_literal_elem_kind(arg.elements or []))
    if isinstance(arg, F.DictExpr):
        # A pair blob, and the VALUES are what a subscript of it yields — the
        # same reader `container_literal_elem_kind` is, deliberately NOT nested
        # for a dict's element word (a key the literal never wrote is a slot
        # nothing initialised).
        return list_kind(container_literal_elem_kind(arg))
    if isinstance(arg, F.Comprehension) and getattr(arg, "kind", "list") != "dict":
        # The comprehension half of `is_dict_expr`, because a dict comprehension
        # parses as a `Comprehension` with `kind == "dict"` and not as a
        # `DictExpr` — and a dict IS a counted blob on this path, so claiming
        # nothing for it would be safe but claiming a LIST for it would not.
        #
        # The BARE kind, and deliberately so where the literal rows above name
        # their element: the element of a comprehension is an expression over its
        # own generator scope (`[k for k in d]`'s element is the loop target),
        # and this function is a module-level shape reader with no `ValueKinds` to
        # ask that scope with. `list_elem_kind` of the bare prefix is `None`, so
        # `subscript_element_kind` still declines to name an element kind and
        # every consumer that reads one keeps the answer it had — while `len`,
        # truthiness and `printf`'s operand reader, which want only "this is a
        # `[count][e…]` blob", are answered by it.
        return list_kind(None)
    if isinstance(arg, F.CallExpr) and isinstance(arg.func, F.IdentExpr):
        name = arg.func.name
        ann = (rets or {}).get(name)
        if ann and annotation_base_name(ann) in STRING_TYPE_CTORS:
            return STR_KIND
        returns_container = getattr(rets, "returns_container", None)
        if returns_container is not None and returns_container(name):
            # The BARE prefix and not the values' kind: the caller cannot see
            # inside what the callee built, so this states the REPRESENTATION
            # and nothing about the elements.
            return LIST_PREFIX
    return None


def _declared_value_shape(ann):
    """The KIND a DECLARED annotation states, or None when it states none.

    **The same two rows `_parameter_argument_shape` reads off a callee's
    declared RETURN TYPE, asked of a PARAMETER's annotation instead**, because
    the two are one claim about one word: `String`/`str` is a `char *` and a blob
    type is a `[count][…]` frame whose first word is its count. A reader that
    answered `-> String` and not `: String` would decide that a string is a fact
    about how a function was WRITTEN and not about what it was handed, and
    `def outer(s: str): return helper(s)` would be the shape that proved it.

    `None` for an annotation that names nothing this path can represent a value
    of, and it goes into the claim set rather than being dropped — see the veto
    rule on `parameter_kinds_by_call_site`. `Pointer[T]` is deliberately not a
    blob here, and `BLOB_TYPE_NAMES` is what says so; a pointer's width is
    `pointer_pointee`'s question and a `list` kind here would move a `len` onto
    the wrong reader.

    An ABSENT annotation is not this function's business: an unannotated
    parameter's evidence is its call sites, and `_param_list` reports it as a
    missing annotation rather than as a declared type that states nothing.
    """
    if not ann:
        return None
    if annotation_base_name(ann) in STRING_TYPE_CTORS:
        return STR_KIND
    if return_type_is_blob(ann):
        return LIST_PREFIX
    return None


def _agreed_parameter_kind(seen):
    """The one kind a set of claims agrees on, or None.

    A set with a `None` in it agrees on nothing — that is the veto rule, and it
    is unchanged. Everything else is the pre-existing rule (`len(seen) == 1`)
    with ONE addition, which the bare-name references made necessary rather than
    optional: a claim set can now hold both `list` and `list:int`, because one
    site may hand over a literal (which states its element kind) while another
    reaches the value through a `: List[Int]` annotation (which cannot see inside
    the callee's container and so states only the representation —
    `_parameter_argument_shape`'s own reason for the BARE prefix).

    Those two are not a disagreement: they are one representation stated at two
    levels of detail, and the merge keeps the DETAIL the claims agree on. Sites
    that disagree about the element kind keep the representation and withhold the
    element kind, which is the same direction as the bare prefix — a reader that
    needs an element kind (`subscript_element_kind`) gets `None` and refuses,
    where a guess would be a wrong element. `list_kind` / `list_elem_kind` /
    `is_list_kind` are the three readers this is spelled with, so it cannot drift
    from how a kind is written down or read back.
    """
    if not seen or None in seen:
        return None
    if len(seen) == 1:
        return next(iter(seen))
    if all(is_list_kind(k) for k in seen):
        elems = {list_elem_kind(k) for k in seen}
        return list_kind(elems.pop()) if len(elems) == 1 else LIST_PREFIX
    return None


# How deep a chain of NAMES this reader will follow from a call site's argument to
# the value the chain names.  A cycle is already an answer (`agreed`'s `active`
# set), and this is the bound for the other shape the cycle guard cannot see: a
# straight line of `var a2 = a1; var a3 = a2; …` long enough to exhaust the
# interpreter's stack, which would be a traceback where every other undecidable
# answer in this file is a refusal.  Sixteen is far past any real chain — the
# longest this corpus needs is two hops — and the bound is enforced in
# `agreed`, which is the one place the chain is walked.
MAX_PARAMETER_KIND_DEPTH = 16


def parameter_kinds_by_call_site(functions, rets=None) -> dict:
    """`{function: {parameter: kind}}` — agreed over EVERY call site.

    Unanimity is the whole of the answer, and it is the same rule every other
    flow-INsensitive table in this file uses (`struct_frame_slot_candidates`,
    `callees_returning_containers`): a name whose definitions or whose call sites
    disagree answers no single question, and the disagreement is resolved by
    claiming nothing rather than by picking the first or the majority. A name
    with NO call site is absent from the table entirely — nothing observed it, so
    nothing is claimed, which is what keeps a module of never-called helpers
    paying nothing.

    **A call site that says NOTHING is one of the claims**, which is the clause
    that makes this a table about the whole image rather than about the majority
    of its call sites: `_parameter_argument_shape` returns None for an
    expression with no shape of its own, None goes into the set, and a parameter
    with one opaque call site claims nothing at all. That is the conservative
    direction and it is the one that matters here — this reader cannot claim a
    parameter is a list when some call this build cannot read passes it
    something else.

    ## A BARE NAME at the call site is followed to where it was bound

    `_parameter_argument_shape` reads the argument's own SHAPE, and a name has
    none — so before this, `f(some_local)` claimed nothing and every name
    reached through one was a word. Measured on both architectures, the shape
    the sweep filed it on (the parameter-kind fixpoint sweep note; §4's last
    paragraph, and the limitation this module's own header listed first):

        def helper(t):  return len(t)
        def outer(s):   return helper(s)
        main:          outer("qq")

        build: len(t) is len() of a value classified as 'int', and an integer
        has no length …                       # both architectures, byte-identical

    A bare name is now a REFERENCE to the name in the CALLER, resolved by the
    same unanimity rule and to the same evidence, so the chain is a fixpoint over
    the image's names rather than a walk from inside one function — which is what
    keeps the answer independent of which function the emitter reached first.
    That order-dependence is the reason the header named this as not to be done
    naively, and it is why the answer is computed here, in one reader, over the
    whole `functions` dict both backends already pass in, rather than by asking
    the CALLER's `ValueKinds` from inside the callee's.

    A reference resolves by a DECLARATION if the name has one and by the SOURCE
    if it does not, and which is which is a fact about the name rather than a
    choice per site:

      * **a declaration decides, and it decides ALONE** — a parameter's
        annotation and a `var x: T` are one statement about the value, and
        `_declared_annotations` (the reader `ValueKinds` asks for the same
        question in the same function) is what sees both. An annotation this
        path cannot map is a `None`, and a `None` is a veto, which is
        `ValueKinds`'s own answer for the same name;
      * **with no declaration, a PARAMETER is answered by its call sites** —
        which is this function's own row, so `outer`'s parameter is answered by
        whoever calls `outer` and the chain ends where the source states a
        value;
      * **and with no declaration, a LOCAL is answered by the statements that
        bind it** (`_binding_values`) — the same reader `ValueKinds`' own
        flow-insensitive map uses, and read the same way: a site with no stated
        expression is a `None` and a `None` is a veto.

    **The first rule is a bug this reader had, and the measurement is the reason
    it is written down.** An initializer is not a type: `var q: Pointer[Int64] =
    s` was read as whatever `s` held, so a `Pointer[Int64]` reached the reader as
    a `char *` two hops later, `p.value()` stopped being intercepted as a
    dereference (`DEREFERENCE_TRY_NAMES`) and was refused four questions from
    the construct it is about. `ValueKinds._bind_value` takes the annotation for
    exactly this reason, and now so does this.

    A body rebinding of a PARAMETER is deliberately not evidence here, and the
    asymmetry is the point: what the caller PASSES does not change because the
    callee assigned to its own parameter afterwards, so unioning `_binding_values`
    into a parameter's row would let `var u = t + 1` retract the kind of every
    call site that passes a string.

    A CYCLE claims nothing (`agreed`'s `active` set) and a chain deeper than
    `MAX_PARAMETER_KIND_DEPTH` does too, which is the same answer a cycle gets in
    `func_kind`'s depth limit and in every other recursion guard in this file: a
    word is what an undecidable answer looks like, and it is the direction that
    refuses rather than the one that guesses.

    It was `string_parameters_by_call_site` and returned only `STR_KIND`, which
    is the one row the truthiness of an unannotated `char *` parameter needed;
    the container row is the same evidence read for the blob the parameter is,
    and keeping two functions would have meant two copies of the unanimity walk
    over call sites — the shape two disagreeing copies produce everywhere else in
    this file.

    **What it can return is the set of rows `_parameter_argument_shape` has, and
    it used to be the STRING one that mattered:** a `char *` arriving from a
    caller is a pointer, and the "a word is an integer" default read it as a
    number (`def f(s): if s:` called `f("")` printed 1 where CPython prints 0). A
    counted BLOB arriving from a caller has the same problem for the same reason
    and the answer is the same shape of evidence — the callers agree — so the
    container row is here rather than in a second table beside this one. That
    row's ANNOTATED half (`def total(xs: List[Int])`) was already answered
    without this table — `ValueKinds.kind_of` asks `declared_param_kind` for an
    `INT_KIND` parameter, and an annotation naming a container maps to a counted
    blob — so only the unannotated spelling was ever live here, and the two are
    pinned together in `test_formal_run.py`'s
    `both_arch_len_of_a_container_annotated_parameter` (the guard) and
    `both_arch_len_of_an_unannotated_parameter_every_call_site_passes_a_list`
    (the fix), with `len_of_a_list_parameter_needs_every_site_to_agree` pinning
    the unanimity rule from the other direction.
    """
    by_name: dict = {}
    for fn in functions or ():
        name = getattr(fn, "name", None)
        if name:
            by_name.setdefault(name, []).append(fn)
    # `(callee, parameter) -> {kind | None}` — what the call sites' own ARGUMENT
    # SHAPES say, which is the whole of the pre-existing walk.
    claims: dict = {}
    # `(callee, parameter) -> {(caller, name)}` — the arguments that are a bare
    # NAME, kept apart because they are not claims at all: they are references to
    # a name in the caller, and resolving one is the fixpoint below. They stay out
    # of `claims` so that a reference which resolves to nothing lands as the same
    # `None` an unreadable expression lands as, and a reference which resolves
    # RETRACTS that veto instead of being added beside it.
    passed: dict = {}
    for caller in functions or ():
        caller_name = getattr(caller, "name", None)
        for call in iter_nodes(getattr(caller, "body", None) or []):
            if not isinstance(call, F.CallExpr):
                continue
            if isinstance(call.func, F.SubscriptExpr):
                continue          # a specialization: the brackets shift
            callee = call_callee_name(call.func)
            if callee is None or callee not in by_name:
                continue
            args = list(getattr(call, "args", None) or [])
            kwargs = list(getattr(call, "kwargs", None) or [])
            if any(isinstance(a, F.UnaryOp) and a.op in ("*", "**")
                   for a in args):
                continue
            names = _positional_parameter_names(by_name[callee])
            if kwargs and args:
                continue          # mixed: the positionals bind the rest
            pairs = list(zip(names, args)) if not kwargs else \
                [(k[0], k[1]) for k in kwargs if k[0] in names]
            for pname, arg in pairs:
                if isinstance(arg, F.IdentExpr) and caller_name:
                    passed.setdefault((callee, pname), set()).add(
                        (caller_name, arg.name))
                    continue
                claims.setdefault((callee, pname), set()).add(
                    _parameter_argument_shape(arg, rets))
    # A parameter's OWN DEFAULT is a claim on its kind, on exactly the footing a
    # call site's argument is. `def f(x="plain")` states what `x` holds as
    # plainly as `def f(x: String)` does, and its one call site `f()` says
    # NOTHING about it (the call-site walk above finds no argument to read), so
    # without this the parameter fell through to "a word is an integer" and the
    # emitter materialized a `char *` into a slot the callee was told held a
    # number. Measured on both architectures: `def f(x="plain"): return x;
    # print(f())` printed a pointer where CPython prints `plain`, and
    # `if x == "plain"` was refused with "compares a NUMBER with a string".
    #
    # The unanimity rule then does the rest, which is why this is a CLAIM rather
    # than a decision: a default that disagrees with a call site contributes a
    # second shape and the parameter claims nothing, exactly as two disagreeing
    # call sites do. Only a positional parameter's default is evidence — a
    # keyword-only parameter cannot be bound by a positional call site, and
    # `_positional_parameter_names` is the reader that says which names those
    # are, so the two tables cannot disagree about binding order.
    for callee, defs in by_name.items():
        names = _positional_parameter_names(defs)
        if not names:
            continue
        for fn in defs:
            for pname, expr in (getattr(fn, "param_defaults", None)
                                or {}).items():
                if pname not in names:
                    continue
                shape = _parameter_argument_shape(expr, rets)
                # A default the shape reader cannot classify (`None`, a name,
                # an arithmetic expression) states NOTHING about the kind and
                # must not join the set: a `None` in the unanimity set is a
                # VETO, and `def f(x=None)` called once as `f("plain")` is a
                # program CPython runs whose string kind the call site already
                # establishes. Only a default that says what it holds (`"plain"`,
                # `7`, a container literal, a `-> String` call) is a claim.
                if shape is not None:
                    claims.setdefault((callee, pname), set()).add(shape)
    # `(caller, name) -> {annotation | None}` — the DECLARATION of a name, for the
    # node question "what does this name hold in the functions called `caller`".
    # A name two definitions of `caller` disagree about (a parameter in one and a
    # local in another, or two different annotations) is a set of more than one
    # entry, which the unanimity rule below answers as "nothing" — the same
    # answer `struct_frame_slot_candidates` gives a layout disagreement.
    annotations: dict = {}
    parameters: set = set()
    for name, defs in by_name.items():
        for fn in defs:
            for p in _param_list(fn):
                pname = p[0] if isinstance(p, (tuple, list)) else p
                parameters.add((name, pname))
            # `_declared_annotations` rather than the parameter list above, so a
            # `var q: Pointer[Int64] = s` is a DECLARATION here for the same
            # reason it is one in `ValueKinds` — see `agreed`'s own comment.
            for pname, anns in _declared_annotations(fn).items():
                annotations.setdefault((name, pname), set()).update(anns)
    memo: dict = {}
    sites_memo: dict = {}

    def _binding_sites(fn, name):
        key = (id(fn), name)
        if key not in sites_memo:
            sites_memo[key] = _binding_values(fn, name)
        return sites_memo[key]

    def agreed(node, active, depth=0):
        """The kind `(caller, name)` holds, or None; memoised over the image.

        The memo is what makes this a FIXPOINT rather than a walk: the same node
        reached from two parameters is walked once, `active` is what makes a
        cycle an answer rather than a recursion, and neither depends on the order
        the emitter reached the functions in — which is the whole of the
        objection the header raised to reading the caller's own kinds.
        """
        if node in memo:
            return memo[node]
        if node in active or depth > MAX_PARAMETER_KIND_DEPTH:
            # A cycle, or a chain past the bound: both claim nothing, and both
            # are refusals rather than a hang.
            return None
        active.add(node)
        seen = set()
        anns = annotations.get(node)
        if anns is not None:
            # A DECLARATION decides, and it decides alone. `_declared_annotations`
            # is the reader `ValueKinds` reads for the same question in the same
            # function, and it covers a parameter annotation AND a `var x: T`,
            # because those are one statement about the value — so this branch
            # answers `f(s: str)`, `f(s)` reached through a declared caller
            # parameter, and `var q: Pointer[Int64] = s` the same way.
            #
            # **And that last one is a bug this branch was written to prevent.**
            # The first version asked the BINDING of a local and never its
            # annotation, so `var q: Pointer[Int64] = s` was read as whatever `s`
            # held — measured on both architectures, `read_x(p)` reached through
            # a chain of two such locals came out classified as a `str`, and
            # `p.value()` stopped being intercepted as a dereference
            # (`DEREFERENCE_TRY_NAMES`) and was refused as "a method this path
            # cannot answer" four questions from the construct it is about. An
            # initializer is not a type: `ValueKinds._bind_value` takes the
            # annotation for exactly this reason.
            if len(anns) == 1:
                for only in anns:    # exactly one: `len(anns) == 1` above
                    seen.add(_declared_value_shape(only))
            else:
                seen.add(None)    # two declarations of one name: nothing
        else:
            # No declaration. A PARAMETER's value comes from its call sites —
            # which is this function's own row, so the chain ends where the
            # source states one — and a LOCAL's from the statements that bind
            # it, which is `_binding_values`, the reader `ValueKinds` reads for
            # that question in the same flow-insensitive way.
            for ref in passed.get(node, ()):
                seen.add(agreed(ref, active, depth + 1))
            seen.update(claims.get(node, ()))
            if node not in parameters:
                for fn in by_name.get(node[0], ()):
                    for site in _binding_sites(fn, node[1]):
                        if site is None:
                            seen.add(None)
                        elif isinstance(site, F.IdentExpr):
                            seen.add(agreed((node[0], site.name), active,
                                            depth + 1))
                        else:
                            seen.add(_parameter_argument_shape(site, rets))
        active.discard(node)
        memo[node] = _agreed_parameter_kind(seen)
        return memo[node]

    rows: dict = {}
    for node in list(claims) + list(passed):
        kind = agreed(node, set())
        if kind is None:
            continue
        rows.setdefault(node[0], {})[node[1]] = kind
    return rows



def _positional_parameter_names(defs) -> list:
    """The callee's parameter names, RECEIVER first, in binding order.

    A receiver (`out self`, `self`, `this`) is parameter 0 of the signature and
    is never bound by a call site's argument list, so every index here is one
    before the position it names. `struct_receivers` is the recogniser, and it
    is the same one the arity tables use, so the two cannot disagree about which
    parameter the first argument lands on.
    """
    for fn in defs or ():
        params = [p[0] if isinstance(p, (tuple, list)) else p
                  for p in _param_list(fn)]
        receivers = struct_receivers(fn)
        if not params:
            return []
        return [p for p in params[1:] if p not in receivers] \
            if params[0] in receivers else params
    return []


class ParameterKindReader:
    """`(function name) -> (parameter name) -> kind or None`, computed at most once.

    A class rather than a function returning a closure so the table is built
    LAZILY: `ValueKinds` asks about a parameter only when the parameter has no
    annotation, so a module that annotates everything — and a corpus that mostly
    does — never walks its own bodies for this. One object per image, and both
    backends build it from the same function, which is what keeps the two
    architectures from answering this question differently.
    """
    def __init__(self, functions, rets=None):
        self._functions = functions
        self._rets = rets
        self._table = None

    def table(self) -> dict:
        if self._table is None:
            self._table = parameter_kinds_by_call_site(self._functions,
                                                     self._rets)
        return self._table

    def for_function(self, fn_name):
        """The `param_kind` hook `ValueKinds` asks, bound to one function."""
        return lambda pname: self.table().get(fn_name, {}).get(pname)




# ── What a linked module's export table says about a call ──────────────────
#
# A module dylib is built from a source file, and its MANIFEST is the contract
# it publishes: for every public function, the boundary symbol, the module that
# owns it, and the C signature `doc/ABI.md` records. `formal/build.py` reads
# that manifest to rewrite each call site to the exported spelling; the two
# questions answered here are the ones that read raises but the emitters could
# not.
#
# Both were open, and both were visible as a module that did not work.
#
#   * THE RETURNED VALUE'S KIND. `ValueKinds` classifies a call by asking
#     `func_kind(callee)`, and a callee that is not a function of the unit
#     being compiled has no answer, so a dylib call's result was unclassified.
#     The manifest already says `char * platform_name (void)`, and the emitter
#     already prints what it is told: `print(platform_name())` formatted the
#     POINTER as an integer and printed `4335747904`. The manifest is the
#     declaration; nothing was reading it for this.
#   * THE DOTTED SPELLING. `from mod import f` binds a BARE name, and the flat
#     `{name: symbol}` map answers it. `import mod` binds the module, and
#     `mod.f(...)` spells the same function with a qualifier this path had no
#     table for — so the only Python spelling of a module call that worked was
#     the one that renames what it calls.
#   * AND THE RE-EXPORTED SPELLING, which is the same table with one more
#     source of names. A package `__init__` that is nothing but `from .sub
#     import f` publishes `f` as part of its API and has an EMPTY export trie
#     on purpose (a re-export is not a new definition, so an entry for it in
#     this image's trie would be an address lookup into a file with no code —
#     `build._namespace_library`). So the names a package publishes are its
#     FORWARDINGS, and the dotted table did not have them: `pkg.f(...)` found
#     nothing, was not refused (there was no table to report), and reached the
#     link audit as a dangling symbol — the same function, reachable only
#     through the spelling that renames it. The manifest already recorded the
#     forwarding (`reexports`, with the symbol the defining module really
#     exports); nothing was reading it for this.
#
# Keyed by MODULE IDENTITY, not by bare name, and that is the whole safety
# argument for the dotted table: `mod.f` can only ever reach an export of the
# library built for `mod` — or a name that module explicitly forwards — so two
# modules that both define `helper` cannot cross-bind, and a bare `f()` cannot
# reach either of them through the dotted table. (The flat bare-name map is a
# different, older, coarser answer and stays where it is;
# `bugs/formal/FORMAL_known_limits.md` §1.1 is why a `_CLIB_SYMS` name is not
# advertised there at all.)


def signature_return_type(signature: str) -> str:
    """The return type a C signature string declares, or `''`.

    `char * platform_name (void)` → `char *`. The head is `<return type>
    <name>` and the name is the LAST whitespace-separated token of it —
    qualified (`int64_t probe.maxsize`) or not — so the return type is
    everything before that token. Splitting on the argument list first is what
    makes the name the last token rather than a parameter.
    """
    if not signature:
        return ""
    head = signature.split("(", 1)[0].strip()
    parts = head.rsplit(None, 1)
    return parts[0].strip() if len(parts) == 2 else head


# A scalar that crosses a FORMAL boundary as one 64-bit word. Every name here is
# a C type reflect._c_signature can emit for a value the formal backends pass or
# return in a general-purpose register; `int64_t`/`uint64_t` are already the
# word type and so are deliberately absent.
_FORMAL_WORD_TYPES = (
    r"int8_t|int16_t|int32_t|uint8_t|uint16_t|uint32_t"
    r"|__fp16|float|double|_Bool|bool"
)
_FORMAL_WORD_RE = re.compile(
    r"\b(?:" + _FORMAL_WORD_TYPES + r")\b(?!\s*\*)")


def formal_boundary_signature(signature: str) -> str:
    """The C declaration a FORMAL dylib export actually has.

    `double fadd (double, double)` → `int64_t fadd (int64_t, int64_t)`.

    **A formal value is one 64-bit word, and that is the whole of this
    function.** The `doc/ABI.md` scalar table is the COMPILED (GIMPLE) path's
    declaration — there a `Float64` really is a C++ `double` and clang puts it
    in the platform's FP register file — and the formal backends were
    publishing it unchanged, so a client that generated its declaration from
    the manifest got a declaration the library does not implement. Measured on
    both architectures, on a library whose whole source is three lines
    (`def fadd(a: Float64, b: Float64) -> Float64: return a + b`), called from
    a C program and from `ctypes`:

      * `double fadd (double, double)` — the client puts 1.5 and 2.25 in the FP
        argument registers and reads the answer out of the FP return register.
        The callee reads the GENERAL-PURPOSE argument registers and returns in
        the general-purpose one, so the client read `2.14e-314` on arm64 and
        `6.42e-314` on x86-64, where CPython says `3.75`. The callee's own code
        is not wrong about the arithmetic — `llvm-objdump` shows
        `fmov d0, x0; fmov d1, x1; fadd d0, d0, d1; fmov x0, d0`, so the FP
        registers are an INTERNAL detail of the float operations and the
        boundary is a word at both ends.
      * `int64_t fadd (int64_t, int64_t)` with the two IEEE-754 bit patterns —
        `3.75`, both architectures, from C and from `ctypes`.

    On arm64 the register classes being disjoint is not a subtlety of the
    caller: `D0` and `X0` are separate storage, measured by handing one callee
    `bits(1.5)` in `d0` and watching it read `X0`, and by `fmov d1, x2`
    leaving `x1` at its previous value. A client cannot rely on the aliasing it
    would need to make the two conventions interchangeable, and neither can the
    declaration.

    **What is deliberately NOT rewritten.** A POINTER keeps its spelling, and
    that is not a gap in the table above: a `char *`, a `MojoList *` and the
    `int64_t *` a frame receiver arrives in are all already words, and the
    pointee is information a client needs (`formal/model.py`'s
    `dylib_export_pointer_pointee` reads it to tell a subscriptable buffer from
    an opaque blob, and `uint8_t *` is the case that reaches it). `void` is not
    a value and is not in the list. `int64_t`/`uint64_t` are already the word
    type.

    **A narrow integer is still narrow; only the WORD it rides in is spelled
    wide.** `sxtw x19, w19` on an `Int32` parameter and `and x19, x19,
    #0xffffffff` on a `UInt32` one are the measured entry code, so the callee
    reads the low `w` bits and sign- or zero-extends them: passing the value in
    the low bits of one word is exactly what the platform ABI does with a
    `w`-bit integer in a register, and this function's spelling says so
    without claiming a width the callee does not use. The reason the word
    matters is the one case where a narrow type in the register is NOT enough:
    an `Optional[Int32]` is empty at the word `1 << 32`
    (`optional_none_word`), which is 33 bits, so a declaration that reads `w0`
    returns `0` where the empty case is `4294967296` — `Some(0)` and `None` are
    one value again, which is the exact defect the niche was introduced to
    remove.

    Applied to the METHOD rows too, and it is a no-op there
    (`_formal_exports` publishes `Struct.method` for those, which
    `formal/imports.py`'s `linked_struct_owners` reads the struct name out of),
    so the two cannot drift: one function, both spellings.

    Read by `formal/build.py`'s `_formal_exports` — the ONE place a formal
    dylib's manifest signature is written — and checked end to end by
    `test_formal_interop.py`, which generates a C declaration from the manifest,
    compiles it, and requires the library to compute what CPython computes.
    """
    if not signature:
        return signature
    return _FORMAL_WORD_RE.sub("int64_t", signature)


def split_c_declaration(signature: str) -> tuple | None:
    """`(return type, name, (parameter types…))` out of a C declaration.

    `int64_t add (int64_t, int64_t)` → `("int64_t", "add", ("int64_t",
    "int64_t"))`; `char * name (void)` → `("char *", "name", ())`.

    **None for a declaration this reader cannot take apart**, and that is the
    answer rather than a guess: a head with no name in it (`int64_t` alone), a
    `...` in the argument list (the arity is not in the declaration), or a
    function-pointer parameter (a declaration in its own right, which no rule
    here reads). All three shapes exist — the last two in
    `mojo/backend_gimple/emit_resolve.py`'s own prototype reader — and each of
    them is a place where a caller that invented a parameter list would
    publish a declaration the callee does not implement.

    ONE reader because three callers need it and they must not answer
    differently: `formal_boundary_signature`'s consumers, `method_boundary_
    declaration` below, and the C client in `test_formal_interop.py`, which had
    its own copy of this split before and could therefore disagree with the
    manifest about what a declaration says.
    """
    if not signature or "(" not in signature:
        return None
    head, _, rest = signature.partition("(")
    parts = head.strip().rsplit(None, 1)
    if len(parts) != 2:
        return None
    params = _split_params(rest.rsplit(")", 1)[0].strip())
    if params is None:
        return None
    return parts[0].strip(), parts[1], tuple(params)


def method_boundary_declaration(signature: str, symbol: str,
                                owner=None, method=None) -> str | None:
    """The C DECLARATION a formal method export publishes, or None.

    `int64_t Point_sum (Point *)` → `int64_t corpus_Point_sum (struct Point *)`.

    **The receiver is the only part that changes, and the reason is the
    convention, not this function.** `reflect` spells a method's receiver
    `Struct *`, which is the COMPILED path's declaration (a real C++
    `Struct *self`) and is wrong for a formal boundary in one measurable case: a
    one-field struct's plain `self`, which both formal backends pass BY VALUE.
    Measured, arm64, `Cell.get`:

        0x100000678:  add x19, x0        # the receiver IS argument 0
        0x10000068c:  add x0, x19
        0x100000690:  add sp, sp, #0x20, lsl #12
        0x10000069c:  ret

    and from C, `corpus_Cell_get(10)` is 10 while `corpus_Cell_get(&c)` is
    6126726256 — a pointer read as an integer. The rule is
    `struct_is_one_field(owner) or receiver_writeback_name(method)`: an address
    unless the struct is one field AND the method does not hand its receiver
    back, which is doc/ABI.md's receiver table read off the two functions both
    emitters ask about a receiver. `owner`/`method` of None (a declaration whose
    struct could not be resolved) is the CONSERVATIVE answer — an address — for
    the reason `declared_receiver_writeback` gives: a name resolved to nothing
    must not be guessed into a value.

    **`symbol`, not the name inside `signature`.** The declaration a client
    writes names the BOUNDARY symbol — the trie entry dyld resolves — and
    reflect's own name inside the signature is the same string today
    (`export_csym` reads it out of there), so this is the one place that could
    drift and does not: the symbol is passed in from the manifest row that
    publishes it.

    **The word convention is `formal_boundary_signature`'s, applied to the
    return type and to every non-receiver parameter**, so a `Float64` return is
    the `int64_t` word it crosses as and a `-> List[String]` is the
    `MojoList *` its signature already says. Applying it to the WHOLE string
    would also rewrite the receiver, and `struct Point *` is not a word type so
    that happens to be a no-op — which is a coincidence, not a reason, so the
    receiver is excluded explicitly and the exclusion is what a reader can
    check.

    None rather than a guess when `signature` cannot be split
    (`split_c_declaration`), when there is no receiver to replace
    (`method_receiver_name`), or when `owner` is a struct whose declared field
    the receiver is: a one-field struct's by-value receiver IS that field, so
    its C type is the FIELD's, and a field with no declared type (a class that
    assigns `self.n` in `__init__`) has no C spelling to publish. A method
    whose receiver cannot be resolved therefore publishes no declaration, and a
    client falls back to `signature` — which is what every client did before
    this field existed.
    """
    parts = split_c_declaration(signature)
    if parts is None:
        return None
    ret, _name, params = parts
    if owner is None or method is None:
        # A declaration whose STRUCT could not be resolved has no receiver
        # convention to state, and publishing reflect's parameter list would
        # publish one anyway — so the absent answer is the answer, and a client
        # falls back to `signature` as it did before this field existed. That
        # is the same direction `declared_receiver_writeback` takes for the
        # same reason: a name resolved to nothing must not be guessed into a
        # convention.
        return None
    if method_receiver_name(method) is None:
        # reflect writes a `Struct *` as argument 0 of EVERY method, including
        # one that declares no receiver (`@staticmethod`, or a first parameter
        # that is not a receiver — `method_declares_receiver`'s question). That
        # parameter is not one the callee takes, so a declaration carrying it
        # is a declaration the callee does not implement — the same defect this
        # whole field exists to remove, one shape further on. There is nothing
        # to publish and nothing to correct, so nothing is published.
        return None
    by_address = ((not struct_is_one_field(owner))
                  or receiver_writeback_name(method) is not None)
    if by_address:
        receiver = f"struct {owner.name} *"
    else:
        field = struct_sole_field_name(owner)
        _base, ann, _why, declared = (
            struct_field_declared_type(owner, field) if field
            else (None, None, None, False))
        if not declared:
            return None
        receiver = formal_boundary_signature(_declared_field_ctype(ann))
        if receiver is None:
            return None
    rest = tuple(formal_boundary_signature(p) for p in params[1:])
    spelled = ", ".join((receiver,) + rest) or receiver
    return (f"{formal_boundary_signature(ret)} {symbol} ({spelled})")


# The C type a declared FIELD crosses a formal boundary as, for the one shape
# that needs one: a one-field struct's by-value receiver, whose word IS the
# field's value. Everything here is the WORD, because that is what a formal
# value is and `formal_boundary_signature` is what says so — which is also why
# an `Int32` field spells `int64_t` here and an `Optional[Int32]`'s empty word
# survives. A POINTER keeps its pointee, which is the one row the word
# convention must not sweep up with the value (`dylib_export_pointer_pointee`
# reads it to know a returned buffer is subscriptable).
#
# `None` for an annotation this table has no C spelling for — a struct of this
# module as the field's type, a container, a type parameter — which sends
# `method_boundary_declaration` down its absent-answer path rather than
# publishing a type this table has never heard of. That is the conservative
# direction, and it is the one `struct_field_declared_type` takes when a field
# is declared twice with two different types.
_DECLARED_FIELD_CTYPES = {
    "int": "int64_t", "Int": "int64_t", "Int8": "int64_t", "Int16": "int64_t",
    "Int32": "int64_t", "Int64": "int64_t",
    "uint": "int64_t", "UInt": "int64_t", "UInt8": "int64_t",
    "UInt16": "int64_t", "UInt32": "int64_t", "UInt64": "int64_t",
    "bool": "int64_t", "Bool": "int64_t",
    "float": "int64_t", "float16": "int64_t", "float32": "int64_t",
    "float64": "int64_t", "double": "int64_t",
    "Float16": "int64_t", "Float32": "int64_t", "Float64": "int64_t",
    "String": "char *", "str": "char *",
}

# The same table for a POINTER's ELEMENT, and it is deliberately NOT the same:
# the word convention widens the VALUE a boundary carries, and a pointer's
# pointee is not the value — it is the type of what the address names, which is
# exactly why `formal_boundary_signature` leaves a pointer's spelling alone and
# why `dylib_export_pointer_pointee` reads it. `Pointer[UInt8]` is therefore
# `uint8_t *`, and a client that knows its buffer is one byte wide needs that to
# be true.
_DECLARED_POINTEE_CTYPES = {
    "int": "int64_t", "Int": "int64_t", "Int8": "int8_t", "Int16": "int16_t",
    "Int32": "int32_t", "Int64": "int64_t",
    "uint": "uint64_t", "UInt": "uint64_t", "UInt8": "uint8_t",
    "UInt16": "uint16_t", "UInt32": "uint32_t", "UInt64": "uint64_t",
    "bool": "int64_t", "Bool": "int64_t",
    "float": "int64_t", "float16": "int64_t", "float32": "int64_t",
    "float64": "int64_t", "double": "int64_t",
    "Float16": "int64_t", "Float32": "int64_t", "Float64": "int64_t",
    "String": "char *", "str": "char *",
}


def _declared_field_ctype(ann) -> str | None:
    """The C type a field's DECLARED annotation crosses a formal boundary as.

    A `Pointer[T]` is spelled `<T> *` and everything else is looked up by its
    bare base name, which is `annotation_base_name`'s reduction — the ONE reader
    of what a declared type names, so the struct that reduction decides a
    layout for and the pointee this decides a width for are the same two
    decisions every other reader of a field declaration makes.
    """
    if not isinstance(ann, str) or not ann.strip():
        return None
    base = annotation_base_name(ann)
    if base is None:
        return None
    if base in POINTER_TYPE_CTORS:
        inner = ann[ann.find("[") + 1:ann.rfind("]")] if "[" in ann else ""
        pointee = annotation_base_name(inner) if inner else None
        elem = (_DECLARED_POINTEE_CTYPES.get(pointee) if pointee else None)
        return f"{elem} *" if elem else None
    return _DECLARED_FIELD_CTYPES.get(base)


def dylib_export_return_kind(entry) -> str | None:
    """`STR_KIND` when a manifest export returns a string, else None.

    STRICTLY ADDITIVE, and that is a deliberate limit rather than an
    incomplete table: a `char *` return becomes classified, and every other
    return stays unclassified exactly as it was. Answering `INT_KIND` for
    everything else would look more thorough and would be a new claim — a
    dylib function returning a list blob or a frame address is a word that is
    not an integer, and the existing "unclassified" answer is the honest one
    for it. Only a `char *` is a kind this model can be sure of from the
    signature, because only a `char *` is the one pointer whose pointee the
    emitters already know how to walk.

    **A container return is NOT readable from the signature, and that is the
    half `imported_callee_kind` adds.** `-> List[Int]` and `-> Int` are both
    `int64_t` in the manifest, so the one-word signature cannot say which is
    which — which is exactly why `len(t)` for `t = other_module.triple()`
    refused with "an integer has no length" about a blob (`[3, 14, 0]`) the
    callee built and the caller already reads by subscript.
    """
    if not entry:
        return None
    ret = signature_return_type(entry.get("signature") or "")
    return STR_KIND if ret.replace("const", "").strip() == "char *" else None


# The host exports whose value — or whose CONTAINER's element — is bytes the
# KERNEL supplied, keyed by `(module identity, bare export name)` because that is
# the identity `dylib_callee_export` resolves to and the one `entry` carries.
# Both spellings of a package re-export resolve to the forwarding module, so the
# `fs_*` rows are `(os, fs_cwd)` and not `(os._syscalls, fs_cwd)`; that is the
# manifest's own `module` field and not a naming convention of this table.
#
# EVERY ROW HERE IS A CLAIM ABOUT ONE FUNCTION'S BODY, and each one was read in
# that body rather than inferred from the name. The three families:
#
#   * `readdir(3)` — `listdir`'s blob and its accessor, and `walk`'s blob, whose
#     `_walk_fill` calls `listdir` on each path. `formal/hostmods/os/__init__`
#     `.mojo`'s `_listdir_fill` is the whole proof: `nm = fs_dirent_name(e)`
#     with `e` a `readdir(3)` result.
#   * `getcwd(3)` / `getenv(3)` / the environment — `getcwd`, `getenv`,
#     `getenv_or` and the six `environ_*` accessors, all of which bottom out in
#     `fs_cwd` / `fs_getenv` or read a pair out of a blob `fs_environ_vec`
#     filled from `environ`.
#   * `uname(2)` / `sysctlbyname(3)` — `platform`'s six exports, all of which
#     return `uts_str(U_x)` or `kern_str(MIB)` and nothing else. `node` is a
#     HOSTNAME, which is the row most likely to be non-ASCII on a real machine
#     and the reason `platform` is here rather than only `os`.
#   * `mkdtemp(3)` and `glob`'s directory walk — one new name made by the kernel
#     and one list of names the kernel made, which are the same two shapes
#     `listdir` already covers arriving through two more modules.
#
# **The rows that answer `""` or a `default` are seeded anyway**, and the reason
# is that the build cannot tell which branch ran: `getenv_or(name, default)`
# returns the caller's own bytes when the variable is unset and the kernel's when
# it is set, and `environ_get_or` is the same shape. Refusing `len` over the
# caller's bytes in that case is the conservative direction and it is one row
# of diagnostic text, against a byte answer that would be wrong for the set case
# — which is the case a caller writes the function for.
FOREIGN_BYTES_EXPORTS = {
    ("os", "listdir"): list_kind(FOREIGN_BYTES_KIND),
    ("os", "walk"): list_kind(FOREIGN_BYTES_KIND),
    ("os", "listdir_get"): FOREIGN_BYTES_KIND,
    ("os", "getcwd"): FOREIGN_BYTES_KIND,
    ("os", "getenv"): FOREIGN_BYTES_KIND,
    ("os", "getenv_or"): FOREIGN_BYTES_KIND,
    ("os", "environ_key"): FOREIGN_BYTES_KIND,
    ("os", "environ_value"): FOREIGN_BYTES_KIND,
    ("os", "environ_keys"): FOREIGN_BYTES_KIND,
    ("os", "environ_get"): FOREIGN_BYTES_KIND,
    ("os", "environ_get_or"): FOREIGN_BYTES_KIND,
    ("os", "environ_pop"): FOREIGN_BYTES_KIND,
    ("os", "fs_cwd"): FOREIGN_BYTES_KIND,
    ("os", "fs_getenv"): FOREIGN_BYTES_KIND,
    ("os", "fs_dirent_name"): FOREIGN_BYTES_KIND,
    ("glob", "glob"): list_kind(FOREIGN_BYTES_KIND),
    ("tempfile", "gettempdir"): FOREIGN_BYTES_KIND,
    ("tempfile", "mkdtemp"): FOREIGN_BYTES_KIND,
    ("platform", "system"): FOREIGN_BYTES_KIND,
    ("platform", "node"): FOREIGN_BYTES_KIND,
    ("platform", "release"): FOREIGN_BYTES_KIND,
    ("platform", "version"): FOREIGN_BYTES_KIND,
    ("platform", "machine"): FOREIGN_BYTES_KIND,
    ("platform", "mac_ver_release"): FOREIGN_BYTES_KIND,
    ("platform", "mac_ver_machine"): FOREIGN_BYTES_KIND,
}


def foreign_bytes_export_kind(entry) -> str | None:
    """`FOREIGN_BYTES_KIND` for a host export whose bytes are the KERNEL's.

    ## Why this is a table keyed on `(module, export)` and not a rule

    There is nothing in a declaration, a signature or a call site that says
    "the bytes in this value did not come from this image".  Provenance is not
    in the type system, and the only place in the tree that knows it is the
    BODY of the host module that made the call — `formal/hostmods/os/
    __init__.mojo`'s `listdir` ends in `_listdir_fill(d, b)`, whose body is
    `b[1 + n] = nm` with `nm = fs_dirent_name(e)` and `e` a `readdir(3)`
    result.  That is a fact about one function in one file, so a table is the
    honest shape for it and a rule would be a guess.

    It is a table of the HOST's API and not of the target, which is the
    distinction that keeps it from being a per-target fact: `os.listdir` is
    foreign bytes on every platform this path builds for, and the alternative
    spelling of the same kind — annotating `List[String]`'s element — would be
    a claim about the type that is false for every OTHER `String` in the corpus.

    ## What the value is, per row

    `FOREIGN_BYTES_KIND` for a value, and `list_kind(FOREIGN_BYTES_KIND)` for a
    CONTAINER of them — which is the whole of what makes the element axis work:
    `for x in names` and `names[i]` both read the element kind, so a row that
    returned the bare scalar kind for `os.listdir` would have refused
    `len(names)` (a count field) instead of `len(x)`, which is the construct the
    kind exists for.  The `list:` prefix carries it and `list_elem_kind` reads
    it, exactly as `list:str` does.

    ## What is NOT here, and why each exclusion is right

    * **`os.sep`, `os.curdir`, `os.devnull`, `os.linesep` and the rest of the
      one-word constants.**  They are `malloc`'d copies of literals that are in
      this image's text section, so they are ASCII by the same argument every
      other string on this path is.  `tempfile.gettempprefix` is one too, and
      `platform.architecture_bits` / `architecture_linkage` answer `"32bit"`
      and `"64bit"`.
    * **`glob.escape`, `platform.platform`, `platform.platform_string` and
      `platform.system_alias_*`.**  Their results are compositions of the
      CALLER's own bytes — `_alias_part` picks one of three arguments — so the
      kind of the result is the kind of the arguments and this path does not
      track that.  A row for them would refuse `len` over a string the caller can
      see every byte of, which is the direction this whole kind exists to avoid.
    * **`os.path.join` / `basename` / `dirname` / `splitext`.**  Their results
      are compositions of the CALLER's own bytes, so the kind of the result is
      the kind of the arguments and this path does not track that.  The
      kernel-derived `os.path` exports (`realpath`, `abspath`, `expanduser`) are
      mixed for the same reason and are therefore also absent — a stated gap
      rather than a silent one, and it is what
      `bugs/formal/FORMAL_len_of_a_readdir_name_is_refused_and_needs_a_bytes_kind.md`'s
      Status records as the remainder of this work.
    * **Every `String` in user code**, which is the point of the whole exercise:
      an exemption here would be right for the few kernel strings and wrong for
      the thousands of literals.
    """
    if not entry:
        return None
    return FOREIGN_BYTES_EXPORTS.get(
        (entry.get("module") or "", entry.get("name") or ""))


def imported_callee_kind(entry, declaration, int_names=(), string_names=(),
                         decls=None) -> str | None:
    """What a call ACROSS a dylib boundary produces, or None for "not known".

    The declaration first, then the signature — in that order and with the
    reason written down, because the two answer different questions and only one
    of them can be right about a container.

    A library's C signature is one word, so it can say `char *` (which is why
    `dylib_export_return_kind` exists and why `print(mod.name())` stopped
    formatting a string as a decimal) and it cannot say anything else:
    `-> List[Int]`, `-> Int` and `-> Bool` are all `int64_t`. The callee's own
    `-> T` can, and `declared_type_kind` is the one reader of a declared type in
    this file, so the two backends cannot disagree about what `List[Box]` means.

    **The container answer carries its ELEMENT kind**, because the two consumers
    a returned blob has are a subscript and a `for`, and both ask what the blob
    HOLDS rather than only that it is one: `for x in names: len(x)` refused with
    "an integer has no length" about a `char *` when the annotation said
    `List[String]` and the bare prefix `list` was all that was carried.
    `annotation_type_arg_base` reads the element out of the brackets and
    `declared_type_kind` classifies it — `List[String]` → `list:str`,
    `List[Int]` → `list:int`, `List[Box]` → `list` (a struct of ANOTHER image
    is not a kind this model has, and the bare prefix is the honest answer).

    **Only a container answer is taken from the declaration.** An `-> Int` is
    deliberately NOT claimed, even though the declaration states it, because
    this path cannot tell an integer from a frame address and the unclassified
    answer is the one that refuses rather than guessing; widening this to the
    scalars is a decision with its own blast radius, and the measured gap this
    closes is the container one (`bugs/formal/FORMAL_listdir_no_run_time_sequence.md`'s
    item 1: `len()` of a value the callee's declaration says is a list).

    `declaration` may be None — a library shipped without its sources, or one
    whose manifest predates the contract — and then this is exactly
    `dylib_export_return_kind`, which is the whole of what it could answer
    before.

    **THE FOREIGN-BYTES SEEDING IS ASKED FIRST AND IS NOT A DECLARATION**, which
    is the one thing about it that needs saying here: `foreign_bytes_export_kind`
    reads `(entry["module"], entry["name"])`, so it is a statement about which
    LIBRARY published the name and what that library's body did, where both
    halves of the declaration below are statements about what the SOURCE wrote.
    A declaration cannot be overridden by a table and a table cannot stand in for
    one — `os.listdir` declares `-> List[String]`, which is the honest word for a
    Python-level list of `str` and which CPython agrees with, and the seeded
    answer is `list:fbytes` because of the `readdir(3)` in the body behind it.
    Both are true and they are about different facts, so the seed is asked first
    and the declaration is what everything else falls back to.
    """
    seeded = foreign_bytes_export_kind(entry)
    if seeded is not None:
        return seeded
    ann = getattr(declaration, "return_type", None) if declaration else None
    if isinstance(ann, str):
        kind = declared_type_kind(ann, int_names, string_names, decls)
        if is_list_kind(kind or ""):
            elem = declared_type_kind(
                annotation_type_arg_base(ann, self_type=None),
                int_names, string_names, decls)
            # A scalar element is the answer a subscript and a loop target both
            # ask for; a container element (`List[List[Int]]`) is not one this
            # path can carry, and the bare prefix is the honest thing to leave.
            return list_kind(elem) if elem and not is_list_kind(elem) else kind
    return dylib_export_return_kind(entry)


def imported_optional_param_annotations(fdef) -> dict:
    """`{argument index: the `Optional[T]` annotation}` an IMPORTED callee declares.

    The PARAMETER half of `imported_callee_kind`, and the same discipline: a
    parameter's declared type is a fact about the CALLEE and only the callee's own
    source has it, so a call across a dylib boundary asks this and never infers
    one from the call.

    **The manifest signature cannot answer it, and that is why the DECLARATION is
    the only input.** A library's C signature is one word per parameter, so
    `int64_t` here is `-> List[Int]`, `-> Int`, `-> Bool` and `Optional[Bool]` at
    once — `formal/imports.py`'s `external_declarations` reads the real
    parameter list from the file the library was compiled from for exactly this
    class of question, and `imported_callee_kind` is what already reads it for the
    RETURN.

    **Keyed by ARGUMENT index, not by parameter index, and the receiver offset is
    applied here** rather than at each consumer, because the offset is a property
    of the declaration (`doc/ABI.md`, "The formal backend's receiver convention":
    a method's receiver travels by pointer and is not in the argument list) and a
    consumer that forgot it would substitute the niche for the RECEIVER's
    declared type — which names no `Optional`, so the substitution would never
    fire and the shape would read as answered while doing nothing. That is the
    failure `_optional_call_argument_none`'s own comment records for the in-unit
    reader, and this is the same rule for the cross-module one.

    Only an argument whose annotation IS an `Optional[…]` is in the answer, so a
    consumer asks "is this index mine?" and nothing else. A declaration with no
    positional parameters, one whose receiver spelling is not recognised, or one
    with an arity this path cannot map gives `{}` — the honest "nothing here says
    so", never a guess about a payload's width.
    """
    out: dict = {}
    if fdef is None:
        return out
    shape = function_param_shape(fdef)
    if not shape.positional:
        return out
    offset = 1 if shape.positional[0].split(":")[0].strip() \
        .split()[-1] in ("self", "cls", "Self", "this") else 0
    for i, spelling in enumerate(shape.positional[offset:], start=offset):
        ann = param_annotation(fdef, spelling)
        if optional_payload_annotation(ann) is not None:
            out[i - offset] = ann
    return out


def abi_module_name(dotted: str) -> str:
    """A dotted module name in the ABI spelling its manifest records.

    A manifest keys an export by the module's ABI PREFIX, and a prefix is a C
    identifier, so the dots are flattened: `os.path` is `os_path`, and its
    `join` exports as `os_path_join_2dbb98`.

    This is the ONE place that substitution is written, and the producer side
    is `formal/imports.py`'s `build_module_dylib`, which calls it to name the
    library whose manifest keys the exports by it. That is not a shared helper
    picked for tidiness: the spelling a caller writes (`os.path.join`) and the
    spelling the manifest is keyed by (`os_path`) differ in exactly this one
    documented way, and two copies of the rule are two chances for them to
    disagree — which is a link error in the last image built rather than in
    either of the two functions.

    The name is UNPRECATED: a top-level module's prefix is its own name, which
    is what every non-package module in this tree has, so for them this is the
    identity function.
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", dotted or "")


def dylib_export_module(by_module: dict, qualifier: str) -> dict:
    """The export table of the module a dotted qualifier names, or `{}`.

    Asked of every dotted callee — for the export it names, and to tell "this
    module does not export that" apart from "that is not a module at all",
    which are different answers with different consequences — so both spellings
    are resolved here rather than at the call sites. It reads whatever table it
    is handed, so the same resolution answers for a module's own exports and
    for what it forwards (`dylib_export_tables`).
    """
    if not qualifier:
        return {}
    table = by_module.get(qualifier)
    if table is not None:
        return table
    return by_module.get(abi_module_name(qualifier)) or {}


def dylib_export_tables(dylib_exports: list):
    """`(by_name, by_module, forwarded)` — the three tables a callee is
    resolved through, built once so the two backends cannot disagree.

    `dylib_exports` is the linked libraries' manifest export lists in LINK
    ORDER (what `formal/build.py` hands both emitters), and the three tables
    are the three questions a callee spelling can ask:

      * `by_name` — `{bare name: entry}`, first library on the line winning, so
        a BARE callee (`from mod import f`) resolves to exactly the entry
        `dylib_syms` resolved it to. Built with `setdefault` in link order for
        that reason, and it is the same iteration `dylib_syms` comes from.
      * `by_module` — `{module identity: {bare name: entry}}`, which is what
        makes a DOTTED callee (`import mod`, spelled `mod.f`) resolvable
        without ever consulting a bare name. This is the table that carries the
        safety argument: `mod.f` can only ever reach an export of the library
        built for `mod`.
      * `forwarded` — `{module identity: {bare name: entry}}` again, but for
        the names a module's API is made of by RE-EXPORT rather than by
        definition: a package `__init__` that is nothing but `from .sub import
        f` has a real, public, importable API, and it deliberately has an EMPTY
        export trie (`build._namespace_library` — a re-export is not a new
        definition, so an entry for it in this image's trie would be an address
        lookup into a file with no code). Its manifest records the forwarding
        under `reexports`, and this is where a dotted call to that name is
        answered.

    Every library contributes a `by_module` slot even when it has no exports,
    because "this module is linked and exports nothing" is a distinct fact from
    "that qualifier is not a module at all", and only the first of the two is
    reportable: the second is a value's method (`xs.append`), which is a
    different construct entirely.

    A forwarded entry carries the symbol the DEFINING module really exports
    (taken verbatim from that module's own manifest when the package's library
    was built), so the call binds the definition rather than the forwarding —
    which is the same symbol the BARE spelling binds, so `from pkg import f`
    and `pkg.f` cannot disagree about where `f` lives. Its declared signature
    and its call contract are borrowed from `by_name` when the symbols agree,
    which is what keeps a `char *` result classified as a string for a
    re-exported function exactly as it is for a defined one, and what keeps an
    argument count checked against the same parameter list either spelling
    names. A name with no match in `by_name` keeps an empty signature and no
    contract, which is the honest "the build does not know" — never a guess at
    either that would change how a result is printed or how a call is bound."""
    by_name: dict = {}
    by_module: dict = {}
    forwarded: dict = {}
    libs = list(dylib_exports or [])
    for lib in libs:
        for entry in (lib.get("exports") or []):
            by_name.setdefault(entry.get("name"), entry)
    for lib in libs:
        module = lib.get("module") or ""
        if module:
            by_module.setdefault(module, {})
        for entry in (lib.get("exports") or []):
            by_module.setdefault(entry.get("module") or "",
                                 {}).setdefault(entry.get("name"), entry)
        for name, fwd in (lib.get("reexports") or {}).items():
            if fwd.get("kind") == "type" or not fwd.get("symbol"):
                # A TYPE has no function symbol to forward: it crosses as a
                # layout in the reflection table and reaches the importer as a
                # `StructDef` (`imported_struct_defs`), so there is nothing
                # here for a CALL to bind and nothing to put in this table.
                continue
            # The declared signature is borrowed from the DEFINING name's own
            # entry (`defines`, which equals the key for every re-export that is
            # not an alias), because that is where the definition is: a package
            # that publishes `g` for `f`'s symbol must classify `g`'s result
            # exactly as it classifies `f`'s, or a re-exported `char *` prints
            # as an integer under one spelling and as a string under the other.
            known = by_name.get(fwd.get("defines") or name)
            entry = {"name": name, "symbol": fwd.get("symbol"),
                     "module": fwd.get("module") or module,
                     "signature": (known.get("signature") or "")
                     if known and known.get("symbol") == fwd.get("symbol")
                     else "",
                     "arity": known.get("arity") if known else None,
                     "call": known.get("call")
                     if known and known.get("symbol") == fwd.get("symbol")
                     else None,
                     "forwarded_by": module}
            if module:
                forwarded.setdefault(module, {}).setdefault(name, entry)
    return by_name, by_module, forwarded


def dylib_export_lookup(by_name: dict, by_module: dict, callee: str,
                        forwarded: dict = None):
    """The manifest export a callee name reaches, or None.

    `by_name` is the flat `{bare name: entry}` table in LINK ORDER with
    `setdefault`, so it is the same resolution `formal/build.py` builds
    `dylib_syms` from and the two cannot answer differently about a bare name.
    `by_module` is `{module identity: {bare name: entry}}`, consulted only for
    a DOTTED callee, whose qualifier names the module that has to own the
    export. The qualifier is resolved by `dylib_export_module`, so a package
    submodule (`os.path.join`) is found under the prefix its manifest uses.

    `forwarded` is the same shape for the names a module publishes by
    RE-EXPORT, and it is consulted only after the module's OWN table, because
    a name the module defines itself is its definition and anything else is a
    forwarding of somebody else's."""
    if not callee:
        return None
    if "." in callee:
        module, _, leaf = callee.rpartition(".")
        entry = dylib_export_module(by_module, module).get(leaf)
        if entry is not None or not forwarded:
            return entry
        return dylib_export_module(forwarded, module).get(leaf)
    return by_name.get(callee)


def _respell_aliased_module_qualifier(name: str, aliases: dict) -> str:
    """A dotted call rooted at an import alias, re-spelled at the module.

    `import lib2 as L` spells the call `L.answer`, but every export table is
    filed under the module the alias stands for — `lib2` — so the qualifier
    `L` has to be translated to `lib2` before the table is asked. This is the
    ONE re-spelling both readers of a dotted callee use, `dylib_extern_symbol`
    (which SYMBOL the call binds) and `dylib_callee_export` (whose DECLARATION
    its arguments bind against), so the two cannot answer about different
    modules for the same call.

    Only a MODULE binding is re-spelled, and the discriminator is the
    `imported_bindings` value's own shape: a module import's DEFINING name is
    the module itself (`L -> (lib2, lib2)`), while a `from m import f as g`
    alias's defining name is the FUNCTION (`g -> (m, f)`) and a `g.…` chain is
    a read through a value, not a library qualifier — `defining == module` is
    what tells the two apart. A non-aliased import spells the qualifier as the
    module already (`os -> (os, os)`), so `module != qualifier` excludes it and
    every existing dotted call passes through unchanged. A bare name is
    returned as it came in: the alias for one of those is a BARE local and the
    flat map answers it through `dylib_aliased_export`, not this.
    """
    if not aliases or "." not in name:
        return name
    qualifier, dot, leaf = name.rpartition(".")
    pair = aliases.get(qualifier)
    if pair is None:
        return name
    module_spelling, defining = pair[0], pair[1]
    if (module_spelling and defining == module_spelling
            and module_spelling != qualifier):
        return module_spelling + dot + leaf
    return name


def dylib_callee_export(by_name: dict, by_module: dict, forwarded: dict,
                        aliases: dict, callee: str):
    """The manifest export entry the call to `callee` binds, or None.

    THE ONE resolution of "which export is this callee", and the reason the
    symbol a call is emitted against, the return kind it is classified by and
    the DECLARATION its arguments are bound against cannot disagree about which
    library answered. All three questions have to be asked about the same entry:
    binding `pkg.f`'s call to `f`'s declaration would check the argument count
    against one module's contract and call another's function.

    Two steps, in this order, and the order is `dylib_extern_symbol`'s rather
    than this function's own convenience: the IMPORT ALIAS first, then the
    plain export lookup (a bare name through the flat table, a dotted name
    through its module's own table and then through what that module FORWARDS).
    The alias is a statement about where THIS FILE got the name, so it is the
    more specific of the two and it is what the emitted `BL` binds — asking the
    flat table first would let a library that happens to export the local
    spelling answer for a call that calls somebody else's function.

    **The `forwarded` table is not optional here**, which is the whole reason
    this is a function rather than a call each reader made for itself: a
    package `__init__` that is nothing but `from .sub import f` publishes `f`
    with an EMPTY export table of its own (`build._namespace_library`), so
    `pkg.f` is answered out of `forwarded`. A reader that passed only
    `by_name`/`by_module` — as both backends' `_extern_decl_for` did — found no
    entry, and a call with no declaration is a call whose arguments are passed
    unexamined: `pkg.f(1)` read the second parameter out of whatever the caller
    last left in that register (measured, 80905394 where the callee says 12) and
    `pkg.f(1, 2, 3)` dropped the third and returned the answer to `pkg.f(1, 2)`.
    Both are the cross-module call-arity failure as it was filed for the BARE
    spelling (that doc is deleted with its fix; `bind_call_arguments` had
    already closed it) — so the two spellings of one export disagreed about the
    same contract, and only one of them was checked.

    `None` means nothing on this link line publishes the name, which is the
    caller's cue to keep whatever answer it has for a callee it cannot resolve
    (`dylib_extern_symbol` is the one that turns it into a refusal)."""
    # A module-aliased callee (`L.answer` under `import lib2 as L`) is spelled
    # with the local name, and BOTH lookups below are filed under the module
    # the alias stands for. Re-spelled once, here, so the declaration reader
    # and the symbol reader (`dylib_extern_symbol`) cannot answer about two
    # different modules for the same call.
    callee = _respell_aliased_module_qualifier(callee, aliases)
    entry = dylib_aliased_export(by_name, by_module, callee, aliases)
    if entry is not None:
        return entry
    return dylib_export_lookup(by_name, by_module, callee, forwarded)


def callee_declaration(functions: dict, by_name: dict, by_module: dict,
                       forwarded: dict, aliases: dict, extern_decls: dict,
                       callee: str):
    """The `FunctionDef` that declares the callee `callee`, or None.

    THE one implementation of "whose parameter list is this call bound
    against", for both backends. It is here for the same reason
    `bind_call_arguments` is: the two emitters each want the same answer from
    their own state, and two copies of the answer are two chances for them to
    disagree about a call that is on the boundary this backend exists to make
    sound. It existed twice — `_extern_decl_for` plus `_callee_decl`, verbatim,
    in `arm64_codegen.py` and in `x86_64_codegen.py` — where the drift would
    have been invisible, because both copies were correct on the day they were
    written and nothing in the type system can tell that a caller reads a
    different one.

    Three places, in this order, and the order is the answer rather than an
    implementation detail:

      1. **`functions`**, this image's own definitions. A local definition
         always wins over an import of the same name, which is the same
         precedence `imported_bindings` gives a local definition in the
         importing file.
      2. **`dylib_callee_export`**, which is the SAME two steps in the SAME
         order `_extern_symbol` takes to decide what SYMBOL a call binds — the
         import alias first, then the plain export lookup, the latter reaching a
         re-exported name through `forwarded`. That shared resolution is what
         makes the two agree by construction: the declaration handed to
         `bind_call_arguments` is reached through the export the call actually
         binds, so a call can never be checked against the signature of a
         different library's same-named function, and a name a package
         RE-EXPORTS is found even though the package's own table is empty.
      3. **`extern_decls`**, `{export symbol: FunctionDef}`, keyed by that
         symbol rather than by the name as spelled (`formal/imports.py`'s
         `external_declarations`).

    None means this image can see no declaration for the callee, and the caller
    falls back to passing the arguments as written — which is the honest answer
    for a library with no source behind its manifest, and the right one for a
    raw C symbol whose only declaration is a header."""
    fn = (functions or {}).get(callee)
    if fn is not None:
        return fn
    entry = dylib_callee_export(by_name, by_module, forwarded, aliases, callee)
    if entry is None:
        return None
    return (extern_decls or {}).get(entry.get("symbol"))


def export_call_contract(fn) -> dict:
    """The argument-COUNT contract a library publishes for one of its exports.

    A caller that can read the callee's DECLARATION asks
    `bind_call_arguments`, which is the language's own rule and needs nothing
    published. A caller that cannot — a library shipped without its sources, or
    one whose manifest was written before the declaration could be read back —
    has only what the manifest carries, and `arity` alone is not enough to
    decide anything: `def f(a)` and `def f(a, b=7)` have the same arity and
    opposite contracts for a one-argument call, and `def f(a, *rest)` has a
    bigger one again while accepting any count.

    So the contract is the three facts a count test needs, and they are the
    three `function_param_shape` already knows:

      * `positional` — the parameters an argument INDEX can land on, in order,
        with the names, so a refusal can name them the way the local one does.
        A keyword-only parameter is not in it, because a positional argument
        reaching one is a `TypeError` rather than a count.
      * `required` — the prefix of those with no default. A count below it has
        an argument nothing can supply, and the callee would read it out of
        whatever the caller left in that register.
      * `variadic` — whether the callee has a `*`/`**` tail, which is what
        makes an over-full count legal (the tail is dropped by design,
        `bind_call_arguments`) rather than an arity error.

    A generic is not exported at all (`doc/ABI.md`'s rule, `FORMAL_known_limits.md`
    §1.1), so a comptime parameter is never in one of these lists — which is why
    this can be read straight off `function_param_shape` rather than through a
    second opinion about which parameters a caller supplies."""
    shape = function_param_shape(fn)
    positional = shape.positional
    return {
        "positional": positional,
        "required": [p for p in positional if not shape.has_default.get(p)],
        "variadic": bool(shape.variadic),
    }


def extern_call_count_refusal(callee: str, got: int, entry) -> str:
    """Why an argument count contradicts a cross-module callee, or "".

    The count check for a call whose callee this image cannot read a
    DECLARATION for, which is the only arity question left once
    `bind_call_arguments` has had its turn. Every wording here is the local
    check's, deliberately: `bind_call_arguments` says "too many positional
    arguments (3 for 2 parameter(s); the parameters are ['a', 'b'])" and a
    reader who has seen one must be able to recognise the other, because the
    difference between the two calls is invisible from the source.

    `""` — not an exception — for every case this cannot decide, and there are
    three of them and they are all common:

      * no entry, or an entry with no `call` contract: the runtime dylib's
        exports come from a C header and carry none, and a manifest written
        before the contract existed carries none. A name whose manifest says
        nothing about its shape keeps the behaviour it has always had, because
        a check that fires on an unknown fires on every library and every
        `*args` call;
      * a variadic callee, where the arguments past the fixed ones are `*name`'s
        and are dropped by design. That is `bind_call_arguments`' rule for a
        callee whose declaration IS readable, so a caller that cannot read it
        has to reach the same verdict rather than a stricter one;
      * a count the contract admits, which includes every count that leaves no
        parameter unfilled.

    **A gap the caller cannot fill is a refusal even when the count is legal**,
    and that is the second thing this closes. `with_default(1)` against
    `def with_default(a, b=7, c=9)` names the right number of arguments, and the
    manifest can say that `b` and `c` have defaults — but a default is an
    EXPRESSION in the callee's declaration, and only the declaration has it. So
    a caller that cannot read the declaration cannot materialize it, and the
    callee reads whatever this image last left in those registers: measured,
    `with_default(1)` returning 357586946 where the callee says 179. The
    alternative is to keep passing them.

    The message adds two things the local one has no way to say, because a
    cross-module call has no parameter list in the image being built: the
    MODULE the callee came from, and the manifest's own `signature` string,
    which is the declaration the library was built from and is the one thing a
    reader can check the count against without the source."""
    contract = (entry or {}).get("call")
    if not isinstance(contract, dict):
        return ""
    positional = contract.get("positional")
    if not isinstance(positional, list):
        return ""
    if contract.get("variadic"):
        return ""
    module = entry.get("module") or "another module"
    signature = entry.get("signature") or ""
    where = (f", which {module} published it as `{signature}`"
             if signature else f", which {module} published")
    repair = (f"Rebuild the library where this build can read the module's "
              f"source, or link the module by IMPORT "
              f"(`from {module} import {callee}`), which brings the "
              f"declaration with it")
    if got > len(positional):
        shown = (f"the parameters are {positional}" if positional else
                 "it declares none")
        return (f"call {callee}(): too many positional arguments ({got} for "
                f"{len(positional)} parameter(s); {shown}{where}). The "
                f"callee is compiled into another module, so its parameter "
                f"list is not this image's to read — the count is checked "
                f"against the manifest entry the call binds")
    if got >= len(positional):
        return ""
    required = contract.get("required")
    required = set(required) if isinstance(required, list) else set(positional)
    gap = positional[got:]
    # `required` is the set of parameters with NO default, so membership is
    # the "nothing can fill this" test and its absence is the "a default could,
    # if this image could read the expression" one.
    unfilled = [p for p in gap if p in required]
    defaulted = [p for p in gap if p not in required]
    if defaulted and not unfilled:
        names = ", ".join(repr(p) for p in defaulted)
        verb = "has" if len(defaulted) == 1 else "have"
        return (f"call {callee}(): {got} argument(s) for {len(positional)} "
                f"parameter(s){where}, and {names} {verb} a default that only "
                f"the callee's DECLARATION carries. Nothing writes into the "
                f"registers those parameters would occupy, so the callee "
                f"reads whatever this image last left there — measured, "
                f"`with_default(1)` returning 357586946 where the callee's own "
                f"default says 179. Pass the argument explicitly. {repair}")
    if unfilled:
        names = ", ".join(repr(p) for p in unfilled)
        return (f"call {callee}(): missing required argument(s) {names} — a "
                f"call with {got} argument(s) for {len(positional)} "
                f"parameter(s){where}, and none of {names} has a default to "
                f"fill it. Nothing is written into the register that would "
                f"hold one, so the callee would read whatever this image last "
                f"put there, and the two architectures do not agree about "
                f"what that is. Pass the argument. {repair}")
    return ""


def dylib_extern_symbol(name: str, syms: dict, by_name: dict, by_module: dict,
                        forwarded: dict = None, aliases: dict = None) -> str:
    """The boundary symbol an unbound callee `name` is emitted against.

    THE ONE implementation, shared by both backends' `_extern_symbol`, which
    were two copies of the same decision and therefore two places for them to
    disagree about what a dotted name binds.

    THREE spellings, and the second and third are why this is a function rather
    than a `dict.get`:

      * a BARE name — what `from mod import f` binds — is answered by the
        flat `{name: symbol}` map, first library on the line winning, which is
        `load_dylib_manifests`'s own precedence and stays it;
      * a bare name that is an IMPORT ALIAS — what `from mod import f as g`
        binds — is answered by the export table of the module the alias came
        from, never by the flat map (`dylib_aliased_export`);
      * a DOTTED name — what `import mod` binds, spelled `mod.f` — is
        answered ONLY by the export table of the library built for `mod`, or by
        what that module forwards (`dylib_export_tables`' `forwarded`). Falling
        back to the flat map for a dotted name would let `mod.f` bind some
        other library's `f`, which is the silently-wrong binding the whole
        module-identity mechanism exists to prevent.

    A name that cannot be bound is REFUSED, and the two refusals are different
    facts with different messages. A bare ALIAS whose module does not publish
    the defining name is `dylib_aliased_export_refusal`'s: falling back to the
    local spelling would bind a symbol nothing defines, and the bind audit would
    report it with no idea why. A DOTTED name whose module is linked but does
    not publish the leaf is the message below, which names both halves and lists
    what the module does publish. Both used to fall through to the bare name,
    which produced a BL against a symbol nothing defines and an image that died
    in dyld — the failure this whole mechanism was built to make a build-time
    error instead. It is also what a namespace library's empty trie used to
    produce: a package whose whole API is re-exported had no table to consult,
    so `pkg.f` found nothing, was not refused (there was nothing to report), and
    reached the link audit as a dangling symbol.

    The module is identified by `dylib_export_module`, which knows that a
    manifest keys a package submodule by its ABI prefix (`os.path` → `os_path`)
    — which is what makes `os.path.join(...)`, the spelling 532 measured call
    sites in this tree are written with, resolve at all."""
    if "." not in name:
        entry = dylib_aliased_export(by_name, by_module, name, aliases,
                                     forwarded)
        if entry is not None:
            return entry.get("symbol") or name
        if is_import_alias(name, aliases):
            # An ALIAS whose module does not export the name it stands for.
            # Falling back to the flat map would bind `g` itself, and the bind
            # audit would report an unbound symbol with no idea why. A plain
            # `from m import f` is NOT this case and keeps the audit's own
            # message, which is the one that was always right for it.
            raise CodegenError(dylib_aliased_export_refusal(
                name, aliases, by_module))
        return (syms or {}).get(name, name)
    # A module-aliased callee (`L.answer` under `import lib2 as L`) is spelled
    # with the local name, and the export table is filed under the module the
    # alias stands for. Re-spelled through the SAME helper the declaration
    # reader uses, so the symbol and the declaration the arguments bind against
    # reach the same library.
    name = _respell_aliased_module_qualifier(name, aliases)
    entry = dylib_export_lookup(by_name, by_module, name, forwarded)
    if entry is not None:
        return entry.get("symbol") or name
    module, _, leaf = name.rpartition(".")
    have = set(dylib_export_module(by_module, module))
    have |= set(dylib_export_module(forwarded, module) if forwarded else ())
    if have or _module_is_linked(by_module, forwarded, module):
        shown = ", ".join(sorted(have)[:8]) + (", …" if len(have) > 8 else "")
        if not shown:
            shown = ("nothing — every name this module publishes is "
                     "re-exported, and none of the modules it re-exports "
                     "from publishes that one")
        raise CodegenError(
            f"{name}(): `{module}` is a linked module but it exports no "
            f"`{leaf}`, so the call has no symbol to bind. What it does "
            f"export: {shown}. A name `doc/ABI.md`'s export rule excludes (a "
            f"leading `_`, a generic template, an overload, or a C library "
            f"symbol such as `exit` or `write`) is not advertised, so a module "
            f"that defines one cannot be called by that name. The exclusion is "
            f"measured and settled in bugs/formal/FORMAL_known_limits.md 1.1; a module "
            f"that needs to publish mutable state rather than functions is a "
            f"different gap, written down in "
            f"FORMAL_module_state_no_storage.md (deleted) (deleted) (deleted) (deleted) (deleted) (deleted; fixed by cross-module accessors for writable globals)")
    refusal = dylib_value_member_refusal(name, module, leaf, by_module,
                                         forwarded)
    if refusal:
        raise CodegenError(refusal)
    return (syms or {}).get(name, name)


def dylib_value_member_refusal(name: str, module: str, leaf: str,
                               by_module: dict, forwarded: dict):
    """The diagnostic for `mod.attr.member(...)` where `attr` is a VALUE, or None.

    **THE CHAIN IS ONE LINK TOO DEEP, and it is the shape `os.environ.get(k)`
    has.** `module` here is `os.environ`, which is not a module with a library
    on this link line, so the arms above cannot report anything about it: there
    is no export table for a thing that is not a module, and
    `_module_is_linked` answers False for the same reason. What used to happen
    is that the name fell through to a bare reference, the bind audit caught
    `os.environ.get` as a symbol nothing provides, and the reader was told their
    LINK LINE was wrong — which is the wrong half of the story, and it became
    the wrong half the moment `os` began publishing `environ` at all: before
    that, `module_spine_link_resolves` said `os.environ` resolved to nothing, so
    `check_module_symbols` refused the chain as an ATTRIBUTE READ with a message
    naming the module and what it publishes. Publishing the accessor turned a
    precise refusal into a link-audit one, and that is a diagnostic regression
    caused by a fix, so it is repaired here rather than left.

    The discriminator is the PARENT's own table: `attr` is an export of the
    module one link up (`environ` is a function of `os`), and a function is a
    value, not a library. So `mod.attr.member(...)` is a call through a value,
    which is the shape `FORMAL_module_state_no_storage.md (deleted) (deleted) (deleted) (deleted) (deleted)` §(2) is about, and the
    sentence says that rather than the linker.

    **THE REPAIR IS NAMED, and it is read off the same table.** A module that
    publishes `foo` and also `foo_get`, `foo_set`, `foo_len` has published the
    OPERATIONS on the value it hands back as functions of its own, because a
    dylib publishes functions and cannot publish the object they are called on.
    So the message lists the exports whose name begins with `attr_`, which for
    `os.environ` is the whole of `environ_count` … `environ_value` and is the
    answer rather than a hint. The prefix rule is not a guess about this
    module: it is the only generic statement available about how a host module
    spells an operation on its own value, and it is falsifiable — a module that
    publishes nothing of the sort produces an empty list, which is reported as
    such rather than left out.

    None when `attr` is not an export of the parent, which is the two cases this
    must not touch: `pkg.sub.twice(…)` (a SUBMODULE with its own library, so the
    arms above already answered it) and `pkg.nosuchattribute.twice(…)` (nothing
    publishes `nosuchattribute`, so the link audit is still the honest report —
    `test_formal_module_attr.py`'s `a_spine_link_that_resolves_to_nothing_is_an_
    attribute_read` is that case and pins it).
    """
    parent, _, attr = module.rpartition(".")
    if not attr:
        return None
    ops = set(dylib_export_module(by_module, parent))
    ops |= set(dylib_export_module(forwarded, parent) if forwarded else ())
    if attr not in ops:
        return None
    related = sorted(n for n in ops if n.startswith(attr + "_"))
    if related:
        shown = ", ".join(related[:8])
        if len(related) > 8:
            shown += ", …"
        repair = (f"the operations on it are published as FUNCTIONS of "
                  f"`{parent}`, and those beginning `{attr}_` are they: "
                  f"{shown} — call one of those, passing whatever the "
                  f"`{attr}`-returning function hands back")
    repair = _value_operations_repair(parent, attr, ops, leaf)
    return (f"{name}(): `{module}` is not a module with a library on this "
            f"link line — `{attr}` is a FUNCTION of `{parent}`, so "
            f"`{name}()` is a call through a VALUE and there is no symbol for "
            f"it to bind. A dylib publishes functions, not the objects they "
            f"are called on, so an operation on a value a module hands back "
            f"cannot be spelled as a member of it; {repair}. "
            f"FORMAL_module_state_no_storage.md (deleted) (deleted) (deleted) (deleted) (deleted) (deleted; fixed by cross-module accessors for writable globals) §(2) records why a value "
            f"cannot cross a dylib boundary at all")


def _value_operations_repair(module: str, attr: str, published, leaf: str) -> str:
    """The REPAIR half of the call-through-a-value refusal, from one place.

    **One reader, and it is the substantive half.** A module that publishes `foo`
    and also `foo_get`, `foo_set`, `foo_len` has published the OPERATIONS on the
    value it hands back as functions of its own, because a dylib publishes
    functions and cannot publish the object they are called on. So the repair is
    the list of exports whose name begins `attr_` — which for `os.environ` is the
    whole of `environ_count` … `environ_value`, and is the answer rather than a
    hint. The prefix rule is not a guess about this module: it is the only
    generic statement available about how a host module spells an operation on
    its own value, and it is falsifiable — a module that publishes nothing of the
    sort produces an empty list, which is reported as such rather than left out.

    Two callers, and they are the two SPELLINGS of one fact: the dotted chain
    (`os.environ.get(k)`) and the imported name (`from os import environ` then
    `environ.get(k)`). Before this was shared they were two sentences about one
    capability, which is how the second came to claim a function had "nowhere to
    live" while the first named it correctly.
    """
    ops = sorted(n for n in published if n.startswith(attr + "_"))
    if not ops:
        return (f"`{module}` publishes no function whose name begins "
                f"`{attr}_`, so it publishes no operation on it at all, and "
                f"there is no spelling of `{leaf}` for this path")
    shown = ", ".join(ops[:8]) + (", …" if len(ops) > 8 else "")
    return (f"the operations on it are published as FUNCTIONS of "
            f"`{module}`, and those beginning `{attr}_` are they: {shown} — "
            f"call one of those, passing whatever the `{attr}`-returning "
            f"function hands back")


def imported_function_as_a_value_refusal(name: str, mod: str, fn_name: str,
                                         published, defining: str = None):
    """`from mod import name` then an operation on `name` — or None.

    **The FROM-IMPORT half of `dylib_value_member_refusal`, and it answers the
    same question the same way: is this imported name one the module publishes as
    a FUNCTION?** `environ` is (`os`'s own accessor), and `from os import
    environ; environ()` builds and runs on both architectures — so refusing the
    `.get` with "this name's value is a real global with nowhere to live" is
    false about it: the name crosses, and what cannot cross is the FUNCTION USED
    AS A VALUE. That sentence sends a reader looking for storage for the one name
    in the program that needs none, which is the defect
    `module_attribute_refusal`'s own docstring records for `sys.argv`.

    `published` is `_module_published_names(module, link_line)`: the same
    `dylib_export_tables` walk the emitter's call resolution takes, in the same
    link order, because "does this module publish that name" is a question the
    emitter already asks and a second reading of the manifests is a second answer
    to it. None — and the caller falls through to the generic arm, which is the
    honest report — for a name the module does NOT publish, which is the case
    where the generic sentence is true.

    **`defining` is the ALIAS, and it is the whole of the third case this
    function had.** `from os import environ as e` binds `e`, and the export
    table of `os` is keyed by `environ`, so asking it about `e` answers "no"
    and the generic arm won with the false sentence again — the same defect one
    spelling along, reached by adding four characters to the import. So the
    question is asked about `defining` when there is one, the REPAIR prefix is
    `defining_` (it is the module's own spelling of the operations), and the
    message speaks the LOCAL name, because that is what the reader's own source
    says. With no alias this function's wording is unchanged, which is what lets
    the cases in `test_formal_module_attr.py` stay as they are.
    """
    key = defining or name
    if not published or key not in published:
        return None
    ops = set(published)
    repair = _value_operations_repair(mod, key, ops, f"{name}.…")
    who = f"{fn_name}: " if fn_name else ""
    aliased = (f" under the name `{key}`" if key != name else "")
    return (f"{who}{name!r} is imported from `{mod}`{aliased}, and it is one of "
            f"that module's published FUNCTIONS — importing it and CALLING it "
            f"lowers today (`{mod}.{key}(...)` or `{name}(...)`), so the import "
            f"is not what is refused. What is refused is an OPERATION on it: a "
            f"function is not a value this path can place, so `{name}.…` is a "
            f"call through a VALUE and there is no symbol for it to bind. A "
            f"dylib publishes functions, not the objects they are called on, so "
            f"an operation on a value a module hands back cannot be spelled as a "
            f"member of it; {repair}. "
            f"FORMAL_module_state_no_storage.md (deleted) (deleted) (deleted) (deleted) (deleted) (deleted; fixed by cross-module accessors for writable globals) §(2) records why a value "
            f"cannot cross a dylib boundary at all")



def module_spine_link_resolves(qualifier: str, by_module: dict,
                               forwarded: dict) -> bool:
    """Whether one link on a dotted callee's SPINE is a name that resolves.

    `qualifier` is the chain's spelling from its root down to and including the
    link — `os.path` for the object of `os.path.join(…)`, `os.environ` for the
    object of `os.environ.get(…)`. Two facts make it resolve, and it needs
    either:

      * it names a LIBRARY on this link line (`os.path`, which has its own
        dylib and its own export table). `_module_is_linked`'s own docstring is
        why this half exists as a test rather than as an export lookup: "linked
        and publishes nothing" and "not a module" both answer `{}` through
        `dylib_export_module`;
      * its LAST segment is an EXPORT of the module above it (`os.getenv_or`,
        which is a function of `os` and not a submodule of it).

    **The narrowing that is not this one**, and it is the reason this function
    exists rather than a `name in table` test: "does the parent module publish
    it" alone refuses `os.path.join`. `path` is NOT one of the 28 names the
    formal `os` publishes (measured) — it is a SUBMODULE with its own library,
    and it resolves through the module table, never through `os`'s.

    A link that resolves is exempt from `check_module_symbols`' member-refusal
    arm; one that does not is not, and the refusal that follows names the link
    and prints what the parent module does publish. That is the whole of the
    fix for `os.environ.get(k, '')`, which was reported as a string comparison
    (`v == '1'`, `strcmp`, "the value of `v` as an address") because the
    spine exemption was unconditional and the link-time symbol check lost the
    race to a diagnostic raised during EMISSION.
    """
    if not qualifier or "." not in qualifier:
        # A single-segment qualifier IS the root, and the root is a module by
        # the time anything asks this (`dylib_module_reference` gates on it).
        return True
    parent, _, leaf = qualifier.rpartition(".")
    if _module_is_linked(by_module, forwarded, qualifier):
        return True
    if leaf in dylib_export_module(by_module, parent):
        return True
    return leaf in dylib_export_module(forwarded, parent)


def dylib_module_reference(node, imported) -> str:
    """The module a dotted chain reads THROUGH, or None if it is not one.

    THE ONE recogniser of the shape, and it answers a different question from
    every other reader of a dotted name here. `dylib_export_lookup` answers
    "which EXPORT does this callee bind"; this answers "is the ROOT of this
    chain a module, or is it a value?" — and the second question is what
    `check_module_symbols` needs, because a module root has no register and
    needs none: it is a library on the link line, named by a manifest.

    It walks a `MemberExpr` / `SubscriptExpr` chain down to its `IdentExpr`
    root, the same root the callee exemption collects, and then asks whether
    that root names a module THIS UNIT IMPORTS. Returns the root's name so the
    caller can exempt the root by node identity, exactly as the callee
    exemption does — never by name, because `iter_nodes` has no parent and the
    same spelling is a module root in one position and a genuine local in
    another.

    The gate accepts a PACKAGE PREFIX as well as an exact match, and that is
    the same rule the callee gate uses: `import os.path` binds the name `os`,
    so `os.path.join(…)` roots at a name that is not itself on the list. A name
    that is a dotted PREFIX of an imported module cannot be a value either —
    locals, parameters and module-level names are all bare, and nothing in this
    language puts an attribute on one — so accepting the prefix cannot exempt a
    value read.

    `imported` is `imports.imported_modules(stmts)` — the modules that must be
    on the link line — NOT the export tables. That is deliberate and it is the
    gate `check_module_symbols` already applies to a dotted CALLEE: a target
    with no module mechanism (an ELF image: no dylib form, nothing to link)
    resolves no imports, and exempting a module root there would let an image be
    emitted with a member read of something nothing provides. Empty/None
    imported means the answer is None for every chain, which is the old
    behaviour."""
    parts = []
    cur = node
    while isinstance(cur, (F.MemberExpr, F.SubscriptExpr)):
        if isinstance(cur, F.MemberExpr):
            parts.append(cur.member)
        cur = cur.obj
    if not isinstance(cur, F.IdentExpr):
        return None
    root = cur.name
    for mod in (imported or ()):
        if root == mod or str(mod).startswith(f"{root}."):
            return root
    return None


def _module_is_linked(by_module: dict, forwarded: dict, module: str) -> bool:
    """Whether `module` names a library on this link line at all.

    "Linked and publishes nothing" and "not a module" are different facts, and
    only the first of them is a refusal that can say what the module does
    export: the second is a value's method (`xs.append`), which is a different
    construct with its own answer. `dylib_export_module` cannot tell them apart
    — it answers `{}` for both — so this asks the tables' keys directly, in
    both the dotted and the ABI spelling, which is the same two spellings that
    function resolves."""
    if not module:
        return False
    for tables in (by_module or {}, forwarded or {}):
        if module in tables or abi_module_name(module) in tables:
            return True
    return False




# ── A module's CONSTANTS, read across a dylib boundary ───────────────────
#
# A dylib cannot export a VARIABLE: there is nowhere for one to live, because
# every value a formal program can name lives in a function's own stack scratch
# (`FORMAL_module_state_no_storage.md (deleted) (deleted) (deleted) (deleted) (deleted) (deleted; fixed by cross-module accessors for writable globals)`). But a module-level name the build
# FOLDED to a literal needs no storage, for the reason the in-unit substitution
# already relies on: the module-level sequence is its only writer, and a
# function that writes the name writes a LOCAL of the same name, which shadows
# it. There is therefore exactly one value of that name in the whole program,
# and it is a literal both sides can hold.
#
# So the importer does not need an address for it — it needs the VALUE, and the
# build that compiled the module is the only place that value was ever
# computed. That is what the manifest's `constants` records, and it is why
# `sys.argv` (a list) and `os.sep` (a string literal) come out differently:
# the first has no literal to record and stays refused, the second has one and
# lowers.


def dylib_module_constants(dylib_exports: list) -> dict:
    """`{module identity: {name: value}}` for every linked library.

    Keyed by the same ABI identity the export tables use, so the consumer
    resolves a qualifier with `dylib_export_module` and gets the same two
    spellings (`os.path` and `os_path`) the symbol tables answer. A name two
    libraries both publish as a constant takes the FIRST on the link line,
    which is `load_dylib_manifests`'s precedence for a bare name and the only
    one available here: a dotted read says which module it means, and a bare
    read does not."""
    out: dict = {}
    for lib in (dylib_exports or []):
        module = lib.get("module") or ""
        constants = lib.get("constants") or {}
        if not module or not constants:
            continue
        for name, value in constants.items():
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                # Only what `fold_literal_expr` can produce crosses here, and
                # anything else in a manifest is a producer this path does not
                # understand. Refusing to invent a value for it is the honest
                # answer; the read then falls through to the ordinary
                # module-global refusal, which says so.
                continue
            out.setdefault(module, {}).setdefault(name, value)
    return out


def imported_constant(tables: dict, qualifier: str, name: str):
    """The value a linked module publishes as a constant under `name`, or None.

    None is a refusal and never a zero: a name no module publishes as a
    literal is a real global or a name that does not exist, and those are two
    different mistakes with two different repairs."""
    table = dylib_export_module(tables, qualifier)
    return table.get(name) if table else None


def dylib_module_variables(dylib_exports: list) -> dict:
    """`{module identity: [name, …]}` for the VARIABLES each library declares.

    A module-level name this module's own functions write through `global` is
    not a constant, and it is deliberately absent from `dylib_module_constants`
    even when its module-level statement folded to a literal — the single-writer
    premise a folded constant rests on is false for it, and publishing both
    would let an importer materialize the value the module STARTED at. This
    function is the other half of that decision, and it exists so a consumer can
    NAME the shape instead of guessing it: `module_attribute_refusal` prints
    "the module's own function writes it" for a name in here and "no storage
    for a list, an object or a stream" for one that is not, and those are
    different facts with different repairs.

    **A name with a `__DATA` slot is NOT automatically in here**, which is the
    correction this table needed: the slot exists for a container literal that
    nobody writes, and that name is a constant whose blob the linker places. The
    membership rule is `GlobalSlot.mutable`, set by `collect_global_slots` from
    the unit's statements AND its bodies; `dylib_module_containers` is the other
    half of the split.

    Keyed by the same ABI identity the export and constant tables use, and it
    takes the FIRST library on the link line for a module identity appearing
    twice — the precedence `dylib_module_constants` already applies, so the two
    tables cannot answer differently about one module.
    """
    out: dict = {}
    for lib in (dylib_exports or []):
        module = lib.get("module") or ""
        if not module:
            continue
        names = lib.get("variables") or []
        if not names:
            continue
        out.setdefault(module, [])
        for name in names:
            if name not in out[module]:
                out[module].append(name)
    return out


def dylib_module_variable_names(dylib_exports: list, qualifier: str) -> set:
    """The variable names the module `qualifier` names publishes, for one reader.

    `dylib_export_module` is applied to the variable table so a consumer resolves
    a qualifier exactly as it resolves the export and constant tables — both
    ABI spellings, `os.path` and `os_path` — rather than matching a bare string
    and answering differently from its two neighbours."""
    table = dylib_export_module(dylib_module_variables(dylib_exports), qualifier)
    return set(table or ())


def dylib_module_containers(dylib_exports: list) -> dict:
    """`{module identity: [name, …]}` for the module-level CONSTANTS each library
    lays out in `__DATA` and does not publish as a value.

    The third shape, and the one that was missing: `collect_global_slots` gives a
    `__DATA` slot to a name whose value is a container literal for a reason that
    has nothing to do with a writer — the blob is static data the linker places —
    so such a name is a CONSTANT with a home, and publishing it in `dylib_module_variables`
    made a consumer refuse it as a variable with a `global` write the defining
    module does not contain (measured on both architectures; the split is
    `GlobalSlot.mutable`).

    It is a separate table rather than a boolean beside the variable one because
    the two produce DIFFERENT sentences, and each has to be true: "the module's
    own functions write it through `global`" is false of a constant, and "a
    dylib publishes functions and folded words, so this blob's address does not
    cross" is false of a variable. Keyed by the same ABI identity and taking the
    FIRST library on the line for a module appearing twice, so the three tables
    cannot answer differently about one module.
    """
    out: dict = {}
    for lib in (dylib_exports or []):
        module = lib.get("module") or ""
        if not module:
            continue
        names = lib.get("containers") or []
        if not names:
            continue
        out.setdefault(module, [])
        for name in names:
            if name not in out[module]:
                out[module].append(name)
    return out


def dylib_module_container_names(dylib_exports: list, qualifier: str) -> set:
    """The container-constant names the module `qualifier` publishes, for one
    reader. The `dylib_module_variable_names` shape, asked about the third table
    for the same reason: one qualifier, resolved the same way, by the same
    function — so `pkg.TABLE` and `x.TABLE` cannot get two different
    classifications out of one link line."""
    table = dylib_export_module(dylib_module_containers(dylib_exports),
                                qualifier)
    return set(table or ())


def constant_literal_node(value, line: int = 0, col: int = 0):
    """An AST literal node carrying a constant that crossed a dylib boundary.

    At the READ site's line and column, not the module-level line the value was
    written on: a diagnostic raised after the substitution points at the read,
    which is the line the reader wrote. `folded_literal_node` is the same rule for the
    in-unit case and is deliberately not reused here — it takes a template node
    to copy the position from, and a value that arrived through a manifest has
    no node behind it.
    """
    if isinstance(value, str):
        return F.StringLiteral(value=value, line=line or 0, col=col or 0,
                               is_bytes=False)
    return F.IntLiteral(value=value, line=line or 0, col=col or 0, raw="")




# ── A bare callee bound by an import's `as` ALIAS ──────────────────────────


def is_import_alias(callee: str, aliases: dict) -> bool:
    """Whether `callee` is bound by an `as` in an import, rather than by its
    defining name.

    The distinction decides which refusal applies when the name cannot be bound.
    A plain `from m import f` that cannot be resolved is the long-standing
    "nothing on this link line provides it" case, reported by the bind audit,
    and it is still reported there — re-deriving it here would give a second
    message for one condition. Only a genuine ALIAS is this function's business,
    because the flat `{bare: symbol}` map is keyed by the defining name and so
    cannot say anything about the local one at all.

    `from m import f as f` is not an alias: it binds the same name, and the flat
    map answers it exactly as it answers the unaliased spelling.
    """
    target = (aliases or {}).get(callee)
    return bool(target) and target[1] != callee


def dylib_aliased_export(by_name: dict, by_module: dict, callee: str,
                         aliases: dict, forwarded: dict = None):
    """The export a bare callee reaches THROUGH an import alias, or None.

    `aliases` is `formal/imports.py`'s `imported_bindings` table, keyed by the
    local name and valued by `(module as spelled, defining name)`, so
    `from os.path import exists as pe` is `{"pe": ("os.path", "exists")}`.

    Three questions, and they are asked in this order because each is weaker
    than the one before it — the last one cannot say WHICH module answered:

      1. **Does the module the name was imported FROM define it?** That module's
         own export table, not the flat one: the flat table cannot say which
         module owns a name, so a local alias that happened to collide with
         another library's export would bind that other library's function. The
         alias is a statement about where `pe` came from, so it is resolved
         against that module and nowhere else.

      2. **Does that module FORWARD it?** Same module, and the same reason for
         the same answer, read off `forwarded` rather than `by_module` — which is
         what `dylib_export_lookup` does for the DOTTED spelling of this very
         call, and the omission was the whole of the aliased-re-export bug: a
         package `__init__` is a namespace library with an EMPTY export table
         (`_namespace_library`), so its published names are all in `forwarded`,
         and question 1 above finds nothing for any of them. An `as` on top of
         that made it unreachable, because the name the consumer writes is the
         alias and the flat map is keyed by the DEFINING name. Both spellings of
         one re-export now resolve through the same table.

      3. **Does ANY library on the line export the DEFINING name?** This is the
         name-based dispatch `from m import f` — with no alias at all — already
         uses, and it is the weakest question because it names no module: a
         package `__init__` with an empty export table means `from pkg import
         bump` has to be answered by the submodule's library under `bump`.
         Asking it by the DEFINING name and not by the local one is what keeps
         it from being a hole: `bump` is a real export somewhere on the line,
         where `b` is a name only this file ever used.

    `None` means none can bind it, which is the caller's cue to raise
    `dylib_aliased_export_refusal`. Falling back to the LOCAL spelling — what
    the code did before any of this — is what produced a BL against a symbol
    nothing defines.
    """
    target = (aliases or {}).get(callee)
    if not target:
        return None
    module, defined = target
    entry = dylib_export_module(by_module, module).get(defined)
    if entry is not None:
        return entry
    if forwarded:
        entry = dylib_export_module(forwarded, module).get(defined)
        if entry is not None:
            return entry
    if "." in defined:
        return dylib_export_lookup(by_name, by_module, defined)
    return by_name.get(defined)


def dylib_aliased_export_refusal(callee: str, aliases: dict,
                                 by_module: dict) -> str:
    """Why an aliased callee has no symbol to bind, or "" if that is not it.

    Three answers and three different facts, one of which is an error in the
    PROGRAM rather than in the module, so they cannot share a message:

      * the module is LINKED and exports the defining name — the lookup found
        it, "" is returned, and the caller uses it;
      * the module is LINKED but exports neither the defining name nor anything
        by that bare name anywhere on the line — `doc/ABI.md`'s export rule
        excluded it, which is a fact about the module and is reported as one,
        exactly like the dotted-callee case;
      * the module is NOT on the link line at all — the import did not resolve
        to anything this image carries, and saying "it exports no such name"
        would send the reader to a module that is not even here.
    """
    module, defined = (aliases or {}).get(callee, ("", callee))
    if not dylib_export_module(by_module, module):
        return (
            f"{callee}(): it is bound by an import from {module!r}, but no "
            f"library for that module is on this image's link line, so the "
            f"name it refers to cannot be bound. An import is a DEPENDENCY: "
            f"if the module has no source this backend can compile, the build "
            f"reports that at the import itself rather than here.")
    return (
        f"{callee}(): it is bound by `from {module} import … as {callee}`, and "
        f"neither `{module}` nor any other library on this image's link line "
        f"exports `{defined}`, so the call has no symbol to bind. A name "
        f"`doc/ABI.md`'s export rule excludes (a leading `_`, a generic "
        f"template, an overload, or a C library symbol such as `exit` or "
        f"`write`) is not advertised — and an alias does not make a name "
        f"exposable that was not already, since the alias is a property of "
        f"this file and not of the library.")


def _target_names(target):
    from mojo.middle.boundnames import _lbn_target_names
    return _lbn_target_names(target) if isinstance(target, str) else []


def for_target_tree(target):
    """Parse a for/comprehension target string into a leaf name or nested list.

    `'i'` -> `'i'`; `'(a, b)'` -> `['a', 'b']`; `'a, b'` (the comprehension
    `Generator.target` spelling, no surrounding parens) -> `['a', 'b']`;
    `'(a, (b, c))'` -> `['a', ['b', 'c']]`. Returns None when a leaf is not a
    plain identifier (a `*name` star leaf stays, as `'*name'`, because the
    binding rules for it are the unpacker's and not this reader's).

    This is the recursive SHAPE reader — `fire_compiler.for_target_names` is the
    recursive FLATTENING of the same text, and a lowering that needs to unpack a
    nested group has to have the nesting, or it unpacks the inner group's names
    against the OUTER element and its arity check fires. That was one bug on
    x86-64 (`a, (b, c)` checked a two-element tuple against a three-name
    target) and this is the one reader both backends now share.

    Uses the parser's own top-level split (`fire_compiler.target_slots`, which
    drops the empty slot a 1-tuple target's trailing comma leaves) and its own
    group peel, so `'d[a, b]'` — a SUBSCRIPT target, one name whose brackets
    contain a comma — is not torn into two.
    """
    if not isinstance(target, str):
        return None
    t = target.strip()
    inner = F._target_group_inner(t)
    if inner is not None:
        parts = F.target_slots(inner)
    else:
        parts = F.target_slots(t)
        # `'(a)'` normalizes in the parser to `'a'`, so a group-less text with
        # no top-level comma is a single leaf and not a one-element tree.
        if len(parts) <= 1:
            if t.startswith("*"):
                rest = t[1:].strip()
                return "*" + rest if rest.isidentifier() else None
            return t if t.isidentifier() else None
    tree = []
    for p in parts:
        child = for_target_tree(p)
        if child is None:
            return None
        tree.append(child)
    return tree if tree else None


def for_target_leaves(tree) -> list:
    """Leaf names of `for_target_tree`'s output, nested groups flattened.

    A star leaf keeps its `*`, so the caller's identifier check refuses it —
    a `for`/comprehension target is validated by this walk rather than by
    `boundnames._lbn_target_names`, which STRIPS the star and would pass a
    `*rest` through to a store under a name nothing allocated. `_tuple_target_key`
    makes the same refusal of a starred tuple ASSIGNMENT target, and this is the
    loop's half of that rule. Both backends read this, so a starred leaf is one
    refusal rather than arm64 lowering it and x86-64 refusing it.
    """
    if isinstance(tree, list):
        out = []
        for child in tree:
            out.extend(for_target_leaves(child))
        return out
    return [tree]


def _comprehension_target_names(target) -> list:
    """The names ONE generator target binds, in source order.

    A comprehension's target is a `str` (`fire_compiler.ComprehensionFor`
    carries it as one), an `IdentExpr`, or a tuple/list of them for a nested
    generator — the three shapes `_bind_target` already splits, and the same
    three `_lbn_target_names` reads for a `for` statement. It is spelled out
    here rather than called so that a target this cannot describe contributes
    NO name: a scope that claimed a name it cannot classify would be a claim
    about a slot whose element it never looked at.

    A tuple target's names all get the ITERABLE's element kind, which is one
    level too coarse for `[[1, 2], [3, 4]]` unpacked into `a, b` (each of them
    holds an integer). That limit is the `for` statement's too and for the same
    reason — deriving it needs the element's own element kind, which
    `_kind_of_nested_elements` collapses — so it is left as one imprecision
    rather than two.
    """
    if isinstance(target, str):
        return [target]
    if isinstance(target, F.IdentExpr):
        return [target.name]
    if isinstance(target, (F.TupleExpr, F.ListExpr)):
        return [e.name for e in (getattr(target, "elements", None) or [])
                if isinstance(e, F.IdentExpr)]
    return []


def scope_lookup(scopes, name: str):
    """`(found, kind)` for `name` in a stack of comprehension scopes.

    INNEST first, and the order is the whole of the answer: a nested
    comprehension's target shadows the enclosing one's for every site inside it,
    which is the same rule `comprehension_generator_scopes`' cumulative maps
    encode and the reason the emitters keep a STACK rather than one merged map.
    A scope that has the name and cannot say what it holds returns `(True, None)`
    rather than falling through, because falling through would answer about the
    enclosing scope's binding of a name the inner one has already rebound.
    """
    for scope in reversed(scopes):
        if name in scope:
            return True, scope[name]
    return False, None
