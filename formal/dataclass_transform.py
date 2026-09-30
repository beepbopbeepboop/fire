"""`dataclasses` for the formal backends: a COMPILE-TIME transform, not a module.

## The layer, and why it is this one

The task is to decide whether CPython's `dataclasses` belongs in a Mojo
`formal/hostmods/dataclasses.mojo` (a runtime library, like `os`/`sys`/`struct`)
or in the formal FRONT END as a transform. This file is the argument, and every
claim in it is a measurement on this tree.

**A Mojo module cannot implement it.** `dataclasses` is a decorator transform
over a CLASS, and a formal value is one 64-bit word (or a frame address) with no
type tag, so a callee cannot be handed a class and asked to decorate it. The
three measurements that settle it:

    # 1. a decorator applied to a class is DROPPED, silently, by both backends
    $ cat .tmp/dc/q1.py
    def deco(cls):
        printf("DECO CALLED\\n")
        return cls
    @deco
    class P: a: int
    def main(n): p = P(1); printf("a=%d\\n", p.a); return 0
    $ python3 fire.py build --formal --no-prove -o q1 .tmp/dc/q1.py && ./q1
    Built: q1  [arm64/macho]
    a=1                      <- "DECO CALLED" never printed
    $ echo $?
    0

  So a `dataclasses.mojo` exporting `def dataclass(cls): ...` would be a symbol
  nothing calls: the decorator is dropped before the front end ever looks at it.
  This is `bugs/COMPILE_FAIL_decorator_application_dropped.md`, and it is why
  `@dataclass` has to be handled where the class is, not where a function is.

    # 2. what a decorator DOES change is the class's own layout and equality,
    #    and those are already this backend's struct semantics
    $ cat .tmp/dc/t6.py
    class P1: a: int          # no decorator at all
    ...
    $ python3 fire.py build --formal --no-prove -o t6 .tmp/dc/t6.py && ./t6
    1 2 5                     # P1(1), P2(2) under @deco("X"), P3() with a: int = 5

  A plain class on this path already constructs by filling declared fields in
  DECLARATION ORDER from positional arguments — which is exactly what
  `@dataclass`'s generated `__init__` does for the positional case. The
  transform's construction half is therefore a NO-OP against a bare struct, and
  the only two things `@dataclass` adds that a bare struct does not have are
  `__eq__` over the fields and the OPTIONS (`frozen`, `order`, `eq`, `repr`,
  `init`, `kw_only`, `match_args`, `slots`, `weakref_slot`, `unsafe_hash`).

    # 3. `==` on a bare struct is an ADDRESS compare, and `@dataclass` makes it
    #    a FIELD compare — so that is the one thing that must be rewritten
    $ cat .tmp/dc/aa1.py     # One has one field, Two has two
    ...
    $ ./aa1
    one=1 two=0               # One(5)==One(5) is True (one word, value-equal);
                             # Two(1,2)==Two(1,2) is False (two frames, addresses)

  and CPython's `@dataclass` says True for both. The rewrite that fixes it is
  measured in `formal/dataclass_transform.rewrite_equality` and pinned by
  `test_dataclasses_formal.py`.

**So: the transform lives here, in the front end, and the import resolves
without a dylib.** `formal/imports.py` gets a third tier,
`FRONTEND_PROVIDED_MODULES`, whose members name a module the front end
implements at compile time: the import is legal, nothing goes on the link line,
and no `formal/hostmods/` file exists to be found by a search root. That last
part is load-bearing — a Mojo `dataclasses.mojo` anywhere the gimple resolver
searches would capture `import dataclasses` in the compiler's own sources, which
is the measured `os.sep` failure in `formal/imports.py`'s `_HOSTMODS_ROOT`
comment.

## What is implemented, and what is refused, and why

Implemented (each pinned by a case in `test_dataclasses_formal.py`):

  * `@dataclass` / `@dataclasses.dataclass`, bare or called with no options, on
    a class whose fields are all `name: T` or `name: T = <literal>`. The class
    lowers as a struct with field-filling construction, which is CPython's
    generated `__init__` for the positional case.
  * `field(default=LITERAL)` in a field position, lowered to the literal it
    wraps. `field(default_factory=F)` is REFUSED: a factory is a call per
    instance and this path has nowhere to keep the result.
  * Field-wise `==` and `!=` over a `@dataclass` class, rewritten to the
    conjunction/disjunction of per-field comparisons.
  * `eq=False`, which is CPython's "use the inherited `__eq__`", and on this
    path the inherited one IS the address compare — so it is honoured by
    leaving the comparison alone.
  * A user-declared `__eq__`, `__repr__` or `__init__` in the class body, which
    CPython keeps in preference to the generated one (measured: `R1 own __eq__
    wins: True`, `R2 own __repr__: U!`, `1 user_init -> 5`).

Refused, each with the reason measured rather than asserted:

  * `frozen=True` — the write side. `b.x = 2` must raise `FrozenInstanceError`,
    and a field store on this path is a plain store (`_store_var`), so there is
    no place to refuse it. Refusing the CONSTRUCT is the only honest answer: an
    image that accepted the store would be wrong silently, which is the outcome
    this backend exists to prevent.
  * `order=True` — `<`/`>` over fields. Same argument as `frozen`, one operator
    wider: the ordered compare is synthesised, not stored.
  * `repr=True` (the default) and `__repr__` synthesis — measured: `printf("%s",
    c)` and `str(c)` SEGFAULT on a struct receiver today (`.tmp/dc/r1.py`,
    `r3.py`). The generated `C(x=1)` is not the default `object.__repr__`, so
    this cannot be waved through as "the same as a bare class".
  * `init=False`, `kw_only=`, `match_args=`, `slots=`, `weakref_slot=`,
    `unsafe_hash=`, `cache_hash=` — each changes the class's shape or its
    generated surface in a way field-filling construction does not express.
  * `__post_init__`, `InitVar` — a hook with no representation.
  * INHERITANCE from another dataclass. Measured: `class C(A)` parses with
    `bases=['A']` and the backend's struct has no base-class field merge, so
    `C(1, 2)` would fill C's own fields and silently drop A's.
  * The runtime REFLECTION half — `is_dataclass`, `fields`, `asdict`,
    `astuple`, `replace`, `__dataclass_fields__`, `getattr(x, f.name)`. This is
    what `ownership_check.py` and `cpp_core.py` actually call, and it cannot be
    done here: all three ask what a VALUE's type is, and a formal value is one
    word (or a frame address) with no type tag. Measured: passing a struct
    receiver into a call is already refused by `frame_receiver_escape_refusal`
    (`.tmp/dc/u1.py`), so even a perfect `fields()` could not be called. See
    `bugs/FORMAL_dataclass_runtime_reflection.md` for the full argument and the
    exact next step; each of those names is refused BY NAME here, so the
    diagnostic says which capability is missing instead of the import failing
    three layers up.

## Why refusing is the deliverable and not a shortfall

`formal/imports.py`'s rule for the whole area: a refusal must be TRUE, and a
construct that cannot be lowered EXACTLY is refused rather than approximated.
`@dataclass` is a construct whose generated methods are half-representable on
this path (construction is, `__eq__` is after a rewrite, `frozen`/`order`/
`repr` are not). The subset above is what this backend can lower exactly, it is
tested against CPython on the same programs, and the rest is named.
"""

import fire_compiler as F


# The module name this transform implements. Read by `bound_module_names` to
# decide which names in a file came from the import, which is what stops
# `check_reflection_calls` refusing an unrelated object's `.fields`.
MODULE_NAME = "dataclasses"


# ── what counts as the decorator ────────────────────────────────────────────
#
# Four spellings, all of which occur in the corpus this closes:
#
#   @dataclass                      formal/types.py, type_system.py
#   @dataclasses.dataclass          ownership_check.py, fault_tolerance.py
#   @dataclass(frozen=True)         formal/types.py
#   @dataclass(<options>)           any
#
# The first two are stored by `fire_compiler`'s decorator block as a plain
# STRING (measured: `STRUCT A decorators: ['dataclass']`, `STRUCT D decorators:
# ['dataclasses.dataclass']`) and the called form as a `CallExpr` (measured:
# `CallExpr(func=IdentExpr(name='dataclass'), args=[], kwargs=[('frozen',
# BoolLiteral(value=True))])`). Both are matched by the trailing name, which is
# what makes a `from dataclasses import dataclass as dc` / `import dataclasses
# as dcls` spelling work without a separate case: both leave the name spelled
# `dataclass` at the end of a dotted path.
DECORATOR_NAME = "dataclass"


def decorator_target(d) -> str:
    """The trailing name of a decorator, whatever shape it was stored in.

    `''` for anything that is not a plain name, so a caller can ask
    `if decorator_target(d) == 'dataclass'` and get False for `@staticmethod`,
    for `@property`, and for anything this file has not heard of.

    Four shapes occur, and all four are measured off this tree's parser:

      * `'dataclass'`                    — a bare name, stored as a STRING
        (`STRUCT A decorators: ['dataclass']`);
      * `'dataclasses.dataclass'`        — a dotted name, also stored as a
        string (`STRUCT D decorators: ['dataclasses.dataclass']`), which is
        why the answer is the trailing component and not the whole spelling;
      * `IdentExpr('dataclass')`         — the `func` of a CALLED decorator;
      * `CallExpr(IdentExpr('dataclass'), args, kwargs)` — the called form
        itself (`@dataclass(frozen=True)`), whose OPTIONS are read separately
        by `option_of`.

    The dotted STRING and the `IdentExpr` are the two that a `from dataclasses
    import dataclass as dc` / `import dataclasses as dcls` spelling produces,
    and both leave the name spelled `dataclass` at the end — so neither needs a
    case of its own here, which is what the trailing component buys."""
    if isinstance(d, str):
        return d.rsplit(".", 1)[-1]
    if isinstance(d, F.IdentExpr):
        return d.name.rsplit(".", 1)[-1] if isinstance(d.name, str) else ""
    if isinstance(d, F.CallExpr):
        return decorator_target(d.func)
    if isinstance(d, F.MemberExpr):
        return decorator_target(d.member)
    return ""


def is_dataclass_decorator(d) -> bool:
    return decorator_target(d) == DECORATOR_NAME


# ── the options, and what each one costs ───────────────────────────────────
#
# The full CPython `dataclasses.dataclass` signature, so an option this file has
# never heard of is refused BY NAME rather than ignored — a silently dropped
# option is a program that builds and computes something the source did not say.
#
#   The three that are HONOURED, and why each is exact rather than approximate:
#
#   eq=False      CPython leaves `__eq__` inherited, which is identity. On this
#                 path a bare struct's `==` IS an address compare, so leaving
#                 the comparison alone is precisely the inherited behaviour.
#                 (`formal/dataclass_transform_test`: `eq_false_keeps_the_
#                 address_compare`.)
#   repr=False    CPython leaves `__repr__` inherited. The inherited one on a
#                 struct SEGFAULTS today (measured, `r1.py`), so this option
#                 cannot make anything better and is refused rather than
#                 pretended at; the honest repair is the same one `repr=True`
#                 needs, and it is filed.
#   init=False    CPython generates no `__init__`, so `C(1)` is a call to
#                 whatever `C` already had — on this path a call to a name with
#                 no definition. Refused.
#
#   Everything else is refused, each with its own reason; see the module
#   docstring for the measurements. `frozen` and `order` are the two that a
#   reader is most likely to assume work, so they are named first in the
#   message and their refusal says what the write/compare would have to do.
SUPPORTED_OPTIONS = frozenset(("eq",))
REFUSED_OPTIONS = {
    "frozen": (
        "`frozen=True` gives every generated field a setter that raises "
        "FrozenInstanceError, and this path has no place to put that setter: a "
        "field store is a store into the receiver's frame "
        "(formal/arm64_codegen.py's `_store_var`) and there is nothing in that "
        "path that can fail. Accepting the class and then storing to its field "
        "would be a program that builds, runs, and mutates a value the source "
        "says is immutable — a wrong answer with no diagnostic, which is what "
        "this backend refuses rather than produces. Write the class without "
        "`frozen`, or keep the value in a local and never assign to it"),
    "order": (
        "`order=True` generates `__lt__`/`__le__`/`__gt__`/`__ge__` over the "
        "fields. This path has no synthesised comparison to hook: `a < b` "
        "lowers to one flag-setting compare of two words (or two frame "
        "addresses), so a field-ordered compare would need a per-field compare "
        "chain emitted at the `<` site, and the same rewriting that gives "
        "`@dataclass` its field-wise `==` would have to be taught a strict "
        "ordering as well. Compare the fields yourself, or sort on a key"),
    "repr": (
        "`@dataclass` generates `__repr__` as `C(x=1)`, and that is not the "
        "inherited `object.__repr__` this path would otherwise reach: printing "
        "a struct receiver SEGFAULTS on both architectures today (measured: "
        "`printf(\"%s\", c)` and `str(c)` on a two-field struct exit 139). So "
        "there is no representation to generate into, and refusing is the only "
        "honest answer — a `__repr__` that printed a frame address would be a "
        "number the source never wrote. `repr=False` is refused for the same "
        "reason and is not a way around it. Print the fields individually"),
    "init": (
        "`init=False` generates no `__init__`, so `C(1)` is a call to whatever "
        "`C` already had. This path lowers a call to a name this module does "
        "not define as an unbound symbol, and the image would not load. Declare "
        "the fields and construct them in declaration order"),
    "kw_only": (
        "`kw_only=True` puts a field on a keyword-only parameter, and this "
        "path's field-filling construction reads POSITIONAL arguments in "
        "declaration order (formal/build.py's `check_construction_shapes` "
        "refuses a keyword against a struct for exactly this reason). There is "
        "one construction shape here, not two"),
    "match_args": (
        "`match_args` is the tuple a structural pattern match unpacks against. "
        "Pattern matching is not a construct this path lowers, so the tuple "
        "would be a module-level name with nowhere to live "
        "(formal/model.py's `module_global_refusal`)"),
    "slots": (
        "`slots=True` replaces the instance `__dict__` with descriptors. This "
        "path's struct IS its fields, with no `__dict__` to replace, so there "
        "is nothing for the option to change and nothing for it to promise"),
    "weakref_slot": (
        "`weakref_slot` adds a weak-reference slot. There is no weak reference "
        "table on a formal image, and no object header to hang one from"),
    "unsafe_hash": (
        "`unsafe_hash` synthesises `__hash__` from the fields. A frozen "
        "dataclass's hash is the tuple hash of its fields, and this path has no "
        "hash to compute it with: `hash(c)` on a struct receiver is refused "
        "(measured) because it wants the object and a multi-field struct has "
        "no value form"),
    "cache_hash": (
        "`cache_hash` memoises `__hash__` in a slot. There is no `__hash__` to "
        "memoise — see `unsafe_hash`"),
    "frozen_": (   # unreachable; kept out by `_unknown_option`
        "unknown option"),
}


def option_of(decorator):
    """`{name: value_node}` for a CALLED `@dataclass(...)`, `{}` otherwise.

    A bare `@dataclass` has no options and so has nothing to validate; the
    caller treats an empty dict from a bare decorator and an empty dict from
    `@dataclass()` identically, which is right — CPython's `@dataclass()` with
    no arguments is the default configuration, the same as `@dataclass`."""
    if not isinstance(decorator, F.CallExpr):
        return {}
    return {k: v for k, v in (decorator.kwargs or [])}


def option_refusal(name: str, value_node) -> str:
    """The refusal for one `@dataclass(...)` option, or '' if it is supported.

    Returns a MESSAGE rather than raising, so the caller can report every
    offending option at once — a reader who wrote `@dataclass(frozen=True,
    order=True)` should be told about both, not fix one and be told about the
    other. `SUPPORTED_OPTIONS` is consulted first, then `REFUSED_OPTIONS`, then
    the unknown-option branch: an option this file has never heard of is
    refused BY NAME because silently ignoring it produces a program that builds
    and computes something the source did not ask for."""
    if name in SUPPORTED_OPTIONS:
        return ""
    reason = REFUSED_OPTIONS.get(name)
    if reason is None:
        return (f"`@dataclass({name}=...)` is not an option this backend "
                f"implements, and it is not ignored: an option dropped here "
                f"would give a class whose generated surface differs from the "
                f"source's, so the program would build, run, and compute "
                f"something the decorator did not ask for. The options that are "
                f"implemented here are {', '.join(sorted(SUPPORTED_OPTIONS))}")
    if name == "eq" and not _is_false(value_node):
        return ("`@dataclass(eq=True)` generates `__eq__` over the fields, "
                "which is the default and IS what this transform does — write "
                "it as a bare `@dataclass`, or `@dataclass(eq=False)` to keep "
                "the inherited identity comparison")
    return f"`@dataclass({name}=...)` is not lowerable on this path. {reason}"


def _is_false(value_node) -> bool:
    return isinstance(value_node, F.BoolLiteral) and value_node.value is False


# ── reflection: the runtime half, refused by name ───────────────────────────
#
# The names `ownership_check.py` and `cpp_core.py` actually CALL. Each one asks
# what a VALUE's type is, and a formal value is one 64-bit word — or, for a
# multi-field struct, a frame address — with no type tag to ask with. There is
# no representation for the answer, so these are refused at the call site with
# the name of the missing capability rather than left to fail three layers up
# as an unbound symbol.
#
# `__dataclass_fields__` is in the list because `formal/types.py` reads it, and
# it is the same question with a different spelling.
REFLECTION_NAMES = frozenset((
    "is_dataclass", "fields", "asdict", "astuple", "replace", "make_dataclass",
    "__dataclass_fields__",
))


def reflection_refusal(callee: str) -> str:
    """The refusal for a call to one of `REFLECTION_NAMES`, or '' if not one.

    `callee` is the name AS SPELLED (`dataclasses.fields`, or `fields` after a
    `from dataclasses import fields`), so the message names the name the reader
    wrote. The reason is the same for all of them and is stated once here: the
    answer is a function of the value's TYPE, and this path has no type tag on
    a value. `bugs/FORMAL_dataclass_runtime_reflection.md` has the measurement
    and the exact next step; this is the same claim in the place that refuses
    it, so the two cannot drift."""
    bare = callee.rsplit(".", 1)[-1]
    if bare not in REFLECTION_NAMES:
        return ""
    return (
        f"{callee}() asks what a VALUE's type is, and a value on this path is "
        f"one 64-bit word — or, for a struct of more than one field, the "
        f"address of a frame of 8-byte slots — with no type tag attached to it. "
        f"So the answer has no representation here at all: the fields are known "
        f"to the FRONT END, from the class declaration, and there is nothing at "
        f"run time that could report them. This is not the same as the import "
        f"failing, and it is not fixable by making `dataclasses` a runtime "
        f"library: measured, passing a struct receiver into a call at all is "
        f"refused by formal/model.py's `frame_receiver_escape_refusal`, so even "
        f"a perfect implementation could not be reached. Use the field names "
        f"directly — `x.a`, `x.b` — which is what the same source does "
        f"everywhere the value's type is already written down. "
        f"bugs/FORMAL_dataclass_runtime_reflection.md")


def reflection_member_refusal(name: str) -> str:
    """The refusal for READING `x.__dataclass_fields__` (not calling it).

    `formal/types.py:289` spells the same question without a call, so it needs
    its own entry point and the same words; routed through `reflection_refusal`
    so the two cannot say different things about the same missing capability."""
    if name.rsplit(".", 1)[-1] != "__dataclass_fields__":
        return ""
    return reflection_refusal(name)


# ── field() ────────────────────────────────────────────────────────────────
#
# `field(default=LITERAL)` is a wrapper around a value this path already knows
# how to hold — a class-level constant that folds — so it is lowered away to the
# literal. Measured: with the wrapper left in, the class-level constant is a
# CALL and is refused by `module_global_refusal` (".tmp/dc/u2.py"), and with it
# lowered the same class builds and prints the default.
#
# `default_factory` is a call PER INSTANCE, and there is nowhere to keep the
# result: a module-level name has no storage (formal/model.py's no-storage
# rule) and a local built in the constructor's frame dies with it. Refused.

# The nodes a class-level default may be written as. Deliberately a set and not
# `isinstance(x, (int, str))`: the question is whether the FRONT END can fold
# the node to a word, and a node type is what it folds on. A `NoneLiteral` is
# in it because `Optional[int] = None` is a field default in
# `type_system.py`, and `x: T = None` is measured to build (`r2.py`'s
# neighbour case, and `q2.py`'s `a: int = 5` shape).
LITERAL_NODES = (F.IntLiteral, F.FloatLiteral, F.StringLiteral, F.BoolLiteral,
                 F.NoneLiteral)


def lower_field(node):
    """`field(default=LIT)` → `LIT`. Returns (new_value, refusal_message).

    The refusal is returned rather than raised so the caller can report every
    offending field of a class at once. A field that is not a `field(...)` call
    is passed through untouched — including a plain `x: int = 5`, which is
    already what `field(default=5)` means."""
    value = getattr(node, "value", None)
    if not isinstance(value, F.CallExpr) \
            or decorator_target(value.func) != "field":
        return value, ""
    if value.args:
        return None, (
            "`field(<positional>)` takes no positional arguments in CPython "
            "either, so there is no value here to lower to")
    opts = {k: v for k, v in (value.kwargs or [])}
    unknown = sorted(set(opts) - {"default", "default_factory", "init",
                                  "repr", "compare", "hash", "metadata",
                                  "kw_only"})
    if unknown:
        return None, (f"field({unknown[0]}=...) is not a field option this "
                      f"backend implements, and it is not ignored: a dropped "
                      f"option gives a field whose behaviour differs from the "
                      f"source's. The options implemented here are `default` "
                      f"(a literal) and `compare=False`")
    if "default_factory" in opts:
        return None, (
            "`field(default_factory=F)` calls F once per instance, and this "
            "path has nowhere to keep the result: a module-level name has no "
            "storage (formal/model.py's no-storage rule, the same one that "
            "refuses a module-level list), and a local built in the "
            "constructor's frame is reclaimed when the constructor returns. So "
            "the per-instance value has no representation here at all. Write "
            "the value as a class-level `x: T = <literal>`, or build it in the "
            "function that needs it")
    if "init" in opts and not _is_false(opts["init"]):
        return None, (
            "`field(init=False)` keeps the field out of the generated "
            "`__init__`, so `C(1)` fills fewer fields than the class declares. "
            "This path's construction fills declared fields in DECLARATION "
            "ORDER from positional arguments (formal/build.py's "
            "`check_construction_shapes`), with no way to skip one")
    if "kw_only" in opts and not _is_false(opts["kw_only"]):
        return None, (
            "`field(kw_only=True)` puts the field on a keyword-only parameter. "
            "This path has ONE construction shape — declared fields filled in "
            "declaration order from positional arguments — and a keyword is "
            "refused against a struct for exactly that reason")
    if "hash" in opts and not _is_false(opts["hash"]):
        return None, (
            "`field(hash=...)` decides whether the field takes part in the "
            "generated `__hash__`. There is no `__hash__` to decide about on "
            "this path: `hash(c)` on a struct receiver is refused because it "
            "wants the object and a multi-field struct has no value form")
    if "metadata" in opts:
        # A mapping is a run-time object this path has no representation for,
        # and nothing in the five corpus files passes one. Refused rather than
        # ignored, for the reason every other unknown option is.
        return None, (
            "`field(metadata=...)` attaches an arbitrary mapping to the field, "
            "which is stored in the class's `__dataclass_fields__` and read "
            "back through the runtime reflection this path does not have. "
            "There is nowhere for it to live")
    if "default" not in opts:
        # `field()` with no default, or with only repr/compare: the value is
        # the field's declared default, which is nothing, and that is already
        # what an unadorned `x: T` is. Nothing to lower.
        return None, ""
    return opts["default"], ""


def field_refusal(name: str, default, declared_type) -> str:
    """The refusal for a field whose default this path cannot hold.

    Only reached for a default that is not a literal. A literal class-level
    constant is materialized where it is read (formal/build.py's
    `_rewrite_class_constants`) and works — measured, `x: int = 5` builds and
    `P3()` prints 5. A non-literal one is a class-level name with no storage,
    and `model.module_global_refusal` already says so; this exists so the
    message names the FIELD and the dataclass option that put it there, which
    the module-level message does not."""
    if default is None:
        return ""
    if isinstance(default, LITERAL_NODES):
        return ""
    return (f"the default for field {name!r} is not a literal, and a "
            f"class-level default on this path must be one: a formal value is "
            f"one 64-bit word, so the only thing a class-level name can be read "
            f"as is the literal it is written with, and this is a call. Write "
            f"the value at the use site (a literal, or an assignment the "
            f"compiler can see), which is the same program with a "
            f"representation")


# ── the field-wise == / != rewrite ─────────────────────────────────────────
#
# The one thing `@dataclass` adds that a bare struct does not have, and the only
# thing here that is a REWRITE rather than a recognition.
#
# Measured, on the tree this landed on:
#
#   * a bare struct's `==` is a flag-setting compare of the two WORDS, and for
#     a multi-field struct those words are frame ADDRESSES. `Two(1,2) == Two(1,2)`
#     is False (`.tmp/dc/aa1.py`, `two=0`) where CPython's `@dataclass` says
#     True (measured `3 eq -> True False`).
#   * a one-field struct fits in a word, so its `==` is already a value compare
#     and already agrees with CPython (`one=1`). The rewrite is therefore only
#     NEEDED for a struct of more than one field, and applying it to a one-field
#     struct would be a no-op at best.
#   * the per-field comparison chain itself lowers correctly through a function
#     boundary, on a frame receiver, with a parameter-typed base:
#     `a.x == b.x and a.y == b.y` in `def eq(a, b)` builds and prints `1 0`
#     where CPython prints the same (`.tmp/dc/x1.py`, `y1.py`).
#
# so the rewrite is a desugaring into a construct this path already has, rather
# than a new lowering. `!=` is `not (==)` and `not` over a comparison is
# measured (`.tmp/dc/z1.py`).

def comparison_chain(field_op: str, join_op: str, left, right,
                     fields) -> object:
    """`a <op> b` over `fields` → `a.f1 <op> b.f1 <join> a.f2 <op> b.f2 …`.

    `field_op` and `join_op` are separate because `!=` is not `not` over `==`:
    it is De Morgan — `a != b` iff SOME field differs — so it is built from
    `!=` comparisons joined by `or`. The two forms are the same statement, and
    the reason the `not` spelling is not used is mechanical and worth stating:
    the rewrite MUTATES the comparison node in place (it is reached through
    `model.iter_nodes`, which yields no parent to re-point), and a `not` over
    the whole chain would need the node to BECOME a `UnaryOp`, which a
    `BinaryOp` cannot do without a parent to assign through.

    `fields` is the class's field names in DECLARATION ORDER, which is the order
    CPython compares them in (`(self.f1, self.f2) == (other.f1, other.f2)`) and
    which on this path is also the order the fields occupy in the frame."""
    line = getattr(left, "line", 0)
    col = getattr(left, "col", 0)
    result = None
    for name in fields:
        one = F.BinaryOp(
            field_op,
            F.MemberExpr(left, name, line, col),
            F.MemberExpr(right, name, line, col),
            line, col)
        result = one if result is None else \
            F.BinaryOp(join_op, result, one, line, col)
    return result


def inheritance_refusal(name: str, base: str) -> str:
    """The refusal for `@dataclass class C(A)`.

    Measured: `class C(A)` parses with `bases=['A']` and this path's struct has
    no base-class field merge, so `C(1, 2)` would fill C's OWN fields and drop
    A's without a word. CPython's dataclass puts the BASE's fields first, so
    the two disagree on the field ORDER as well as the field SET — and the
    order is what decides which value lands in which slot, so this is a wrong
    answer rather than a missing one. Refused."""
    return (f"{name} inherits from {base!r}, and a dataclass's fields are the "
            f"base class's fields FOLLOWED BY its own (CPython's generated "
            f"`__init__` takes them in that order). This path's struct has no "
            f"base-class field merge at all: the declared fields of {name} are "
            f"the only ones it has slots for, so inheriting would silently drop "
            f"{base}'s — the values would be filled into the wrong slots and "
            f"the program would run and print numbers the source never wrote. "
            f"Declare the inherited fields on {name} itself, or keep "
            f"{base} a plain struct and pass it as a field")


def post_init_refusal(name: str) -> str:
    """The refusal for a `__post_init__` on a dataclass.

    CPython calls it at the end of the generated `__init__`, with the object
    already built. This path's construction is field-filling at the "
    "construction SITE (`S(1, 2)`), with no `__init__` body to run at all —
    a declared `__init__` is refused by name by `check_construction_shapes` —
    so there is no point in the sequence at which a `__post_init__` could be "
    "called. Refused rather than dropped: a dropped hook is a program that "
    "builds and computes something the source did not ask for."""
    return (f"{name} declares __post_init__, which CPython calls at the end of "
            f"the generated __init__ with the object already built. This path "
            f"constructs by filling declared fields at the construction site "
            f"(`{name}(1, 2)`) and runs no __init__ body at all, so there is no "
            f"point in that sequence at which the hook could be called — and a "
            f"dropped hook is a program that builds, runs, and skips work the "
            f"source asked for. Do the work in the function that constructs the "
            f"value, or in a method called on it")


def init_var_refusal(name: str, field: str) -> str:
    """The refusal for an `InitVar[...]` field on a dataclass.

    CPython passes an `InitVar` to `__init__` as a parameter and does NOT make
    it a field: it is not stored, not compared by the generated `__eq__`, and
    not printed by `__repr__`. So a class with one has a field set that "
    "differs from its constructor's parameter list, and this path has exactly "
    "one of those — fields filled in declaration order, which is the same list. "
    Refused."""
    return (f"field {field!r} of {name} is an InitVar, which CPython passes to "
            f"__init__ as a parameter WITHOUT storing it as a field — so the "
            f"constructor's parameters and the class's fields are two different "
            f"lists. This path has one list: declared fields, filled in "
            f"declaration order by the construction site. Declare it as an "
            f"ordinary field, or take it as an ordinary parameter")


# ── the driver: everything above applied to one module ─────────────────────
#
# Split by what each part needs to know, and the split is the reason this is one
# file with three entry points rather than three files:
#
#   `dataclass_classes`  needs the module's StructDefs.
#   `lower_field_defaults` needs the classes, and MUTATES them — it is a rewrite
#                         and must run before anything reads the field defaults.
#   `rewrite_equality`   needs the holder analysis, which only exists inside
#                         `_frame_receivers`, so it is handed that answer.
#
# The import of `M` and `CodegenError` is DEFERRED, inside the two functions
# that need them, and that is not tidiness. `formal/model.py` is deliberately
# leaf-most — `os` and `fire_compiler` only — so the two formal architectures
# cannot drift apart through a shared helper (see the note at the top of
# `formal/model.py`, and `FORMAL_known_limits.md` §4's "One consolidation
# deliberately NOT made"). This module is imported BY `formal/build.py`, which
# already imports both, so a top-level `from formal import model as M` would
# put a second edge into that graph for no gain; the deferred import keeps this
# file readable on its own while adding no import cycle.
def _model():
    from formal import model as M
    return M


def dataclass_classes(stmts: list, structs: list = None) -> dict:
    """`{name: info}` for every top-level StructDef carrying the decorator.

    This is the ONE place the decorator is read, and both the refusals and the
    `==` rewrite consult the table it returns, so a class cannot be a dataclass
    for the refusal that names it and a bare struct for the rewrite that
    computes on it.

    A class that declares its OWN `__eq__` is recorded with that fact rather
    than dropped from the table: CPython keeps the user's `__eq__` in
    preference to the generated one (measured: `R1 own __eq__ wins: True` —
    with `@dataclass class T` defining `__eq__`, `T(1) == T(2)` is True where
    the generated one would say False), so rewriting the comparison for it
    would OVERRIDE a method the source wrote. `own_eq` is what the rewrite
    consults; `own_init` is recorded for the same reason and is reported by
    `check_construction_shapes` downstream."""
    M = _model()
    out = {}
    for st in (structs if structs is not None
               else [s for s in stmts if isinstance(s, F.StructDef)]):
        if not any(is_dataclass_decorator(d) for d in
                   (getattr(st, "decorators", None) or [])):
            continue
        out[st.name] = {
            "struct": st,
            "own_eq": any(getattr(m, "name", None) == "__eq__"
                          for m in M.struct_methods(st)),
            "own_init": any(getattr(m, "name", None) == "__init__"
                            for m in M.struct_methods(st)),
            "eq_false": any(
                is_dataclass_decorator(d) and _is_false(
                    option_of(d).get("eq", None))
                for d in (getattr(st, "decorators", None) or [])),
        }
    return out


def check_dataclass_classes(classes: dict) -> None:
    """Validate every `@dataclass` this module declares. Raises `CodegenError`.

    Three things, in the order a reader hits them:

      1. INHERITANCE. Checked first even though it is the rarer spelling,
         because a base class's fields are dropped SILENTLY, and a silent drop
         is the outcome this backend exists to prevent.
      2. OPTIONS, each by name, each with its own reason, and ALL of them
         reported rather than just the first — a reader who wrote
         `@dataclass(frozen=True, order=True)` should learn about both, not fix
         one and be told about the other.
      3. `__post_init__` and `InitVar`, a hook and a pseudo-field that the
         generated `__init__` has a place for and this path's construction site
         does not.

    Raises `formal.arm64_codegen.CodegenError` because that is what the front
    end's other checks raise (`check_construction_shapes`,
    `check_frame_field_blob_premises`) and because both of `compile_formal`'s
    entry points wrap their check block in `except CodegenError`, so a refusal
    here reaches the user as the one-line diagnostic every other refusal
    produces. Measured on this tree: a refusal raised from `_prepare_functions`
    was classified `backend-crash` by the sweep, which is a verdict for a
    compiler bug — see `formal/build.py`'s `_formal_module_functions`."""
    from formal.arm64_codegen import CodegenError
    M = _model()
    for name, info in classes.items():
        st = info["struct"]
        for base in (getattr(st, "bases", None) or []):
            raise CodegenError(inheritance_refusal(name, base))
        bad = []
        for deco in (getattr(st, "decorators", None) or []):
            if not is_dataclass_decorator(deco):
                continue
            for opt, value in option_of(deco).items():
                why = option_refusal(opt, value)
                if why:
                    bad.append(why)
        if bad:
            raise CodegenError(f"{name}: " + " ".join(bad))
        for m in M.struct_methods(st):
            if getattr(m, "name", None) == "__post_init__":
                raise CodegenError(post_init_refusal(name))
            if getattr(m, "name", None) == "__eq__":
                # Checked here rather than declined in `rewrite_equality`,
                # because a refusal has to be a fact about the FILE and
                # `rewrite_equality` cannot see a class the program never
                # compares — so a class with a user `__eq__` would be accepted
                # and then be wrong the first time it was used. See
                # `own_eq_refusal` for the measurement.
                raise CodegenError(own_eq_refusal(name))
        for f in M.struct_fields(st):
            ann = getattr(f, "type_ann", None)
            if isinstance(ann, str) and "InitVar" in ann:
                raise CodegenError(init_var_refusal(
                    name, getattr(f, "name", None)
                    or getattr(getattr(f, "target", None), "name", "?")))


def lower_field_defaults(classes: dict) -> None:
    """`field(default=LITERAL)` → the literal. A REWRITE, not a check.

    It has to run before anything reads the field defaults, and before
    `_rewrite_class_constants`: a class-level constant is MATERIALISED where it
    is read (formal/build.py), so a `field(...)` left in place is materialised
    as a CALL and refused by `model.module_global_refusal` (measured,
    `.tmp/dc/u2.py`), while the literal it wraps is materialised as the literal
    (measured: the same class with the wrapper lowered builds and prints its
    default). So this is not a convenience — the wrapper is the only thing
    standing between a working class and a refusal."""
    M = _model()
    for name, info in classes.items():
        st = info["struct"]
        for f in M.struct_fields(st):
            fname = (getattr(f, "name", None)
                     or getattr(getattr(f, "target", None), "name", "?"))
            new_value, why = lower_field(f)
            if why:
                raise_from_field(why)
            if new_value is not None:
                f.value = new_value
            bad = field_refusal(fname, getattr(f, "value", None),
                                getattr(f, "type_ann", None))
            if bad:
                raise_from_field(f"{name}.{fname}: {bad}")


def raise_from_field(message: str) -> None:
    from formal.arm64_codegen import CodegenError
    raise CodegenError(message)


def rewrite_equality(fn, holders: set, by_name: dict, classes: dict) -> None:
    """Desugar `a == b` between two values of the same `@dataclass`.

    Called from inside `_frame_receivers`, because that is where a name's STRUCT
    is known: a local's struct is settled by the holder fixpoint and a
    parameter's by the interprocedural edge in the same pass. This function is
    HANDED that answer rather than re-deriving it, which is the same reason the
    pass publishes `fn._frame_candidates` for `model.struct_construction_plan`:
    two recognitions of "is this name a dataclass value" is exactly the pair
    that agrees until the day it does not.

    It fires only when BOTH sides are known holders of the SAME dataclass
    struct, and the cases it declines are all cases where declining is right:

      * a different struct on the right — `A(1) == B(1)` is False in CPython
        for distinct dataclass types, and an address compare also says False;
      * a name that is not a holder at all — a word, a string, an int;
      * a class with its own `__eq__` — CPython keeps the user's;
      * `@dataclass(eq=False)` — CPython keeps the inherited identity compare,
        which on this path is the address compare the codegen already emits.

    It is a REWRITE rather than a new lowering because the thing it rewrites
    into already lowers correctly: `a.x == b.x and a.y == b.y` through a
    function boundary on a frame receiver is measured to build and print
    `1 0` where CPython prints `1 0` (`.tmp/dc/x1.py`, `y1.py`), and `not` over
    a comparison is measured too (`z1.py`)."""
    M = _model()
    if not classes or not holders:
        return
    # `{holder: (struct, fields)}`, computed ONCE per function: the alternative
    # is a scan of the holder table per comparison, which is quadratic in a
    # body for a question with a one-line answer.
    typed = {}
    for name in holders:
        cands = by_name.get(name) or []
        if len(cands) != 1:
            # Zero candidates is a plain word. MORE than one is the
            # agree-or-refuse case `_frame_receivers` reports on its own, and
            # picking one here would compute a comparison from a struct the
            # program might not be holding on this path.
            continue
        st = cands[0]
        info = classes.get(getattr(st, "name", None))
        if info is None or info["own_eq"] or info["eq_false"]:
            continue
        typed[name] = (st, M.struct_field_names(st))
    if not typed:
        return
    for node in M.iter_nodes(fn.body):
        if not isinstance(node, F.BinaryOp) or node.op not in ("==", "!="):
            continue
        left = _typed_dataclass(node.left, typed)
        if left is None:
            continue
        right = _typed_dataclass(node.right, typed)
        if right is None or right[0] is not left[0]:
            continue
        if not left[1]:
            continue
        # `==` is "every field matches" and `!=` is De Morgan's "some field
        # differs". The node is mutated IN PLACE — `iter_nodes` yields no
        # parent, so there is nothing to re-point a replacement through — which
        # is why both arms are `BinaryOp`s and neither is a `not` over the other.
        field_op, join_op = ("==", "and") if node.op == "==" else ("!=", "or")
        chain = comparison_chain(field_op, join_op, node.left, node.right,
                                 left[1])
        node.op, node.left, node.right = chain.op, chain.left, chain.right


def _typed_dataclass(expr, typed):
    """`(struct, fields)` when `expr` is a bare name this function typed.

    A bare name and nothing else: `a.x == b.y` is not a dataclass comparison,
    it is two field reads, and rewriting it would change what the source says.
    A parenthesised name is the same node here — the parser does not keep the
    parentheses — which is correct, because `(a) == b` IS `a == b`."""
    if not isinstance(expr, F.IdentExpr):
        return None
    return typed.get(expr.name)


def check_reflection_calls(functions: list, module_names: set) -> None:
    """Refuse every call to a `dataclasses` reflection name, by name.

    The runtime half of the module — `is_dataclass`, `fields`, `asdict`,
    `astuple`, `replace`, `__dataclass_fields__` — is what `ownership_check.py`
    and `mojo/backend_gimple/cpp_core.py` actually CALL, and it is the half
    that cannot work here. Each of those names asks what a VALUE's type is, and
    a formal value is one 64-bit word — or, for a struct of more than one
    field, the ADDRESS of a frame of 8-byte slots — with no type tag attached
    to it. There is no representation for the answer.

    Why it is not fixable by making `dataclasses` a runtime library, which is
    the question this file exists to answer: measured, passing a struct receiver
    into a call AT ALL is refused by `model.frame_receiver_escape_refusal`
    (`.tmp/dc/u1.py`), and `hash(c)` on a struct receiver is refused for the
    same reason (`.tmp/dc/b1.py`). So a perfect `fields()` could not be
    REACHED, let alone implemented. The fields are known to the FRONT END,
    from the class declaration; there is nothing at run time that could report
    them. `bugs/FORMAL_dataclass_runtime_reflection.md` has the full argument
    and the exact next step.

    `module_names` is the set of names the module bound the module under —
    `dataclasses` from `import dataclasses`, `dc` from `import dataclasses as
    dc`, and the same for a from-import. A name NOT in it is some other
    object's `fields`, and refusing that would be a false claim about a file:
    the check is what makes the diagnostic say "`dc.fields()` needs a type tag"
    rather than refusing every `.fields` in the tree.

    A name reached by a BARE from-import (`from dataclasses import fields`, then
    `fields(x)`) is in the set under its own name, which is why the set is built
    from the import statements rather than only from the module binding."""
    M = _model()
    from formal.arm64_codegen import CodegenError
    for fn in functions:
        for node in M.iter_nodes(fn.body):
            callee = None
            if isinstance(node, F.CallExpr):
                # `dataclasses.fields(x)` — a MemberExpr callee — and
                # `fields(x)` — a bare one, from a from-import. Both spellings
                # occur in the corpus (cpp_core.py uses the first,
                # ownership_check.py both).
                f = node.func
                if isinstance(f, F.IdentExpr) and f.name in module_names:
                    callee = f.name
                elif isinstance(f, F.MemberExpr) \
                        and isinstance(f.obj, F.IdentExpr) \
                        and f.obj.name in module_names:
                    callee = f"{f.obj.name}.{f.member}"
                elif _is_dynamic_attribute(node):
                    # `hasattr(x, "__dataclass_fields__")` — the same question
                    # with the member name as a STRING rather than a member
                    # access, which is how formal/types.py:289 spells it. The
                    # call is to a builtin, not to a name the import bound, so
                    # nothing about the import's spelling reaches here; what
                    # identifies it is the NAME being asked about.
                    if node.args and isinstance(node.args[-1], F.StringLiteral):
                        literal = node.args[-1].value
                        if literal in REFLECTION_NAMES:
                            callee = literal
            elif isinstance(node, F.MemberExpr) \
                    and isinstance(node.obj, F.IdentExpr) \
                    and node.obj.name in module_names:
                # `expr.__dataclass_fields__` — the same question with no call
                # on it.
                callee = f"{node.obj.name}.{node.member}"
            if callee is None:
                continue
            why = (reflection_refusal(callee)
                   if isinstance(node, F.CallExpr)
                   else reflection_member_refusal(callee))
            if why:
                raise CodegenError(f"{fn.name}: {why}")


def _is_dynamic_attribute(call) -> bool:
    """True for `getattr(x, "name")` and `hasattr(x, "name")`.

    The two builtins that take a member NAME as a run-time value, and the only
    two: `vars()['x']` and `operator.attrgetter` are not in this tree's corpus
    and adding a reader for each would be speculative. `setattr` is excluded
    deliberately — it asks the same question but its answer is a WRITE, which
    is refused by the name checker rather than here, and refusing it twice
    would give two messages for one cause."""
    return (isinstance(call.func, F.IdentExpr)
            and call.func.name in ("getattr", "hasattr")
            and len(call.args) >= 2)


def bound_module_names(stmts: list) -> set:
    """Every name this module binds the `dataclasses` MODULE under.

    `import dataclasses` → `{'dataclasses'}`; `import dataclasses as dc` → also
    `{'dc'}`; `from dataclasses import fields` → `{'fields'}` (the imported
    NAME, because a bare call spells it bare). The last one is why this is a set
    of every name the import binds rather than of module bindings only.

    Returns the EMPTY set for a file that does not import `dataclasses`, which
    is what makes `check_reflection_calls` free on every other file in the tree
    — the check is not gated on a flag, it is gated on the import."""
    out = set()
    for st in stmts or []:
        if isinstance(st, F.ImportStmt):
            for name, alias in (st.extra or []) + [(st.module, None)]:
                if name == MODULE_NAME:
                    out.add(alias or name)
        elif isinstance(st, F.FromImportStmt):
            if st.module != MODULE_NAME:
                continue
            for pair in (st.names or []):
                name = pair[0] if isinstance(pair, (tuple, list)) else pair
                if isinstance(name, str) and name:
                    out.add(name)
    return out


def own_eq_refusal(name: str) -> str:
    """The refusal for a `@dataclass` that declares its OWN `__eq__`.

    CPython keeps the user's `__eq__` in preference to the generated one
    (measured: with `@dataclass class T` defining `__eq__`, `T(1) == T(2)` is
    True where the generated one would say False), so the class is LEGAL and
    its meaning is unambiguous. It is refused anyway, and the reason is a
    measurement rather than a policy:

        class Plain:            # no decorator at all
            x: int
            y: int
            def __eq__(self, other): return True
        def eq(a, b):
            if a == b: return 1
            return 0
        # arm64:  eq(p, q) == 0        CPython: 1
        # arm64:  p.__eq__(q) == 1     CPython: 1

    `==` on this path is ONE flag-setting compare of two words
    (formal/arm64_codegen.py's `_emit_binop`) and never dispatches by name, so
    the user's `__eq__` is reachable only as an explicit `p.__eq__(q)` — which
    is the second line, and it is right. Accepting the class would therefore
    produce an image that runs `eq(p, q)` as an address compare and prints 0
    where the source's own method says 1: a wrong answer, silently, from a
    program that did nothing unusual. The same is true of a `__repr__`, and
    `repr` is a worse one because printing a struct receiver SEGFAULTS today
    (measured) rather than merely answering wrongly.

    So: refused, with the repair named. This is the one place where the
    transform declines a class CPython accepts, and it declines it because the
    capability that would make it right — a comparison that dispatches to a
    method — does not exist here, not because the class is unusual."""
    return (f"{name} declares its own __eq__, which CPython keeps in "
            f"preference to the generated one (so the class is legal and its "
            f"meaning is unambiguous). It is refused because `==` on this path "
            f"is one flag-setting compare of two words and never dispatches by "
            f"name: measured, a class with a user __eq__ that returns True "
            f"gives `a == b` as 0 here and 1 under CPython, while an explicit "
            f"`a.__eq__(b)` gives 1 under both. So accepting {name} would build "
            f"an image that runs the comparison as an address compare and "
            f"prints a number the method in the source contradicts — silently, "
            f"from a program that did nothing unusual. Call the method "
            f"explicitly (`x == y` becomes `x.__eq__(y)`), or drop the method "
            f"and let the field-wise comparison this transform generates "
            f"answer it")
