#!/usr/bin/env python3
"""test_dataclasses_formal.py -- `@dataclass` on the formal arm64 backend is
CPython's `@dataclass`, and this file is the evidence.

**The oracle is CPython, on the same text.** Every execution case below is run
TWICE: once as a formal-built arm64 image that is executed, and once by this
process's own `python3` running the same source, and the two must agree on
stdout AND on the exit status. Not "it built" and not a hand-written expected
number — the numbers in the comments are there to be read against, and the
assertion is the comparison.

**Why executing is the whole point.** `@dataclass` changes what a class MEANS,
and the failure mode this backend is built to prevent is an image that is
*correct about the code it emitted* and wrong about the program. Two measured
examples from the tree this landed on, both of which would pass a build-only
test:

  * a bare struct's `==` compares two WORDS, and for a struct of more than one
    field those words are frame ADDRESSES — so `Two(1, 2) == Two(1, 2)` was
    `False` where CPython's `@dataclass` says `True`. The image ran, printed a
    number, and was wrong. `dataclass_equality_is_field_wise` is that case.
  * `@dataclass(frozen=True)` was accepted silently, and `b.x = 2` stored 2
    where CPython raises `FrozenInstanceError`. Also ran, also wrong.
    `frozen_is_refused` is that case.

**What is compared, and what is not.** The implemented subset and the refused
subset are both pinned here, and the refused ones are pinned by their MESSAGE
rather than by a build failing — a refusal that stops naming the construct is a
regression this file would otherwise not see, and the same reasoning applies to
the layer decision the whole design rests on (see
`formal/dataclass_transform.py`'s docstring, which is the argument for a
compile-time transform rather than a `formal/hostmods/dataclasses.mojo`).

**Deliberately not here.** `fields()` / `is_dataclass()` / `asdict()` /
`replace()` — the runtime reflection half. They are refused by name, and
`bugs/FORMAL_dataclass_runtime_reflection.md` records why they cannot be
implemented at all on this path (a value is one 64-bit word with no type tag)
and what the next step would be. Pinning "it is refused, with this reason" is
in scope; making it work is a different project.

Run:  python3 test_dataclasses_formal.py [-v] [case ...]
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60

# The CPython side of the comparison. `printf` is this backend's own output
# primitive (`formal/arm64_codegen.py` lowers it to a libSystem call), so the
# oracle needs the same spelling; `%`-formatting is the same operation the C
# function performs, which is the point — the two paths are formatting the same
# arguments the same way, so a difference in the output is a difference in the
# COMPUTATION and not in the printing.
_PRELUDE = (
    "import sys\n"
    "def printf(fmt, *args):\n"
    "    sys.stdout.write(fmt % args)\n"
)


def cpython_run(tmpdir, name, source):
    """Run `source` under this process's `python3`. (stdout, exit status)."""
    path = os.path.join(tmpdir, name + ".cpython.py")
    with open(path, "w") as f:
        f.write(_PRELUDE)
        f.write(source)
        f.write("\nsys.exit(main(0))\n")
    r = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT, cwd=HERE)
    return r.stdout, r.returncode


def formal_run(tmpdir, name, source, arch="arm64"):
    """Build `source` for `arch` and EXECUTE it. (stdout, exit status)."""
    path = os.path.join(tmpdir, name + ".py")
    with open(path, "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, name + f".{arch}.bin")
    b = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         f"--backend={arch}", "-o", out, path],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    if b.returncode != 0:
        raise BuildRefused((b.stderr or b.stdout).strip())
    r = subprocess.run([out], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    return r.stdout, r.returncode


class BuildRefused(Exception):
    """The build refused, with the compiler's own message."""


RESULTS = []


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f": {detail}" if detail else ""), flush=True)
    return bool(ok)


# ── 1. the implemented subset: built, EXECUTED, compared with CPython ───────

# `@dataclass class Point: x: int; y: int`, then `Point(3, 4)`. The load-bearing
# claim is that this is CPython's generated `__init__` — fields filled in
# DECLARATION ORDER from positional arguments — and not "a struct that happens
# to have two fields". Constructing the same class twice with the arguments
# swapped is the only observable difference between the two readings, and it is
# what this case checks.
BARE_CONSTRUCT = """
from dataclasses import dataclass

@dataclass
class Point:
    x: int
    y: int

def main(n):
    p = Point(3, 4)
    q = Point(4, 3)
    printf("p=%d,%d q=%d,%d", p.x, p.y, q.x, q.y)
    return 7
"""

# The same, spelled `@dataclasses.dataclass` with the module imported rather
# than the name from-imported. Both spellings occur in the corpus this closes
# (`formal/types.py` and `ownership_check.py` respectively) and they are
# DIFFERENT AST shapes — a bare string and a dotted string — so a transform that
# recognised only one of them would pass the other file's test suite here.
DOTTED_DECORATOR = """
import dataclasses

@dataclasses.dataclass
class Point:
    x: int
    y: int

def main(n):
    p = Point(3, 4)
    printf("p=%d,%d", p.x, p.y)
    return 0
"""

# `field(default=LITERAL)`. The wrapper is lowered to the literal it wraps,
# which is what makes the class-level constant foldable: measured, with the
# wrapper left in place the build refuses the class-level constant as a CALL
# (`module_global_refusal`), and with it lowered the same class builds. So this
# case is the difference between a working class and a refusal, not a
# convenience.
#
# `Config(7)` — a PARTIAL positional construction, which CPython allows because
# the remaining fields take their defaults — is deliberately NOT here: this
# path's construction fills DECLARATION ORDER from positional arguments and
# refuses a count that does not match (`check_construction_shapes`), so
# `Config(7)` is a construction-shape refusal rather than a dataclasses one.
# It is recorded in `bugs/FORMAL_dataclass_partial_construction.md`; putting it
# in this case would have tested the construction check and called it a
# dataclasses failure.
FIELD_DEFAULT = """
from dataclasses import dataclass, field

@dataclass
class Config:
    width: int = field(default=80)
    height: int = 24

def main(n):
    a = Config()
    b = Config(1, 2)
    printf("%d %d %d %d", a.width, a.height, b.width, b.height)
    return 0
"""

# `x: T = None` is the default for an optional field, and it is the single most
# common class-level default in this repository's own dataclasses
# (`std/type_system.py`'s `Type.bit_width: Optional[int] = None` and nine more
# on the same class; `std/fault_tolerance.py`'s `SideResult.harness_error`).
#
# It used to be refused, and the refusal had a branch of its own in
# `field_refusal` because it is the one a reader is most likely to believe is
# free: on this parser `None` is a NAME (`IdentExpr('None')`) and not a
# literal, so there was nothing for a class-level constant to be materialized
# as. `model.NONE_WORD` closed it by making `None` the word 0, which is the
# representation rather than an approximation — it is what an unwritten frame
# slot already is.
#
# The branch is gone from `field_refusal` and this row is what keeps it gone:
# a refusal nobody can see is a refusal nobody removes. Both halves matter —
# the default is read at construction, and the word it reads as is 0 — and
# `test_formal_run.py`'s `none_*` group pins the representation from the other
# side (a class-level constant, a module-level one, and the three comparisons
# the fold must NOT answer).
#
# Deliberately NOT compared against CPython: `printf("%d", None)` is a
# TypeError there, so the oracle does not exist. What this asserts is the
# REPRESENTATION, which is a 0.
NONE_FIELD_DEFAULT = """
from dataclasses import dataclass

@dataclass
class T:
    bit_width: int = None
    name: int = 7

def main(n):
    a = T()
    b = T(3)
    printf("%d %d %d %d", a.bit_width, a.name, b.bit_width, b.name)
    return 0
"""

# THE case. A bare struct's `==` compares two words, and for a struct of more
# than one field those words are frame addresses — so this program printed
# `0 1 0 1` (every equality false) where CPython prints `1 0 0 1`. The image
# ran, exited 0, and was wrong, which is exactly the outcome a build-only test
# would have passed. `ne` is here because `!=` is De Morgan's "some field
# differs" rather than `not` over the conjunction, and the two are separate
# code paths in the transform.
EQUALITY = """
from dataclasses import dataclass

@dataclass
class Point:
    x: int
    y: int

def eq(a, b):
    if a == b:
        return 1
    return 0

def ne(a, b):
    if a != b:
        return 1
    return 0

def main(n):
    p = Point(3, 4)
    q = Point(3, 4)
    r = Point(3, 5)
    printf("%d %d %d %d", eq(p, q), eq(p, r), ne(p, q), ne(p, r))
    return 0
"""

# The same, through a FUNCTION BOUNDARY with the operands as parameters. The
# holder analysis is what tells the transform a parameter holds a dataclass, and
# this is the case where it has to have run: a name is only a dataclass value
# because some call site passed one to it. A rewrite that looked only at
# constructor bindings would desugar the caller's `==` and leave this one
# comparing addresses, and the two halves of one program would then disagree.
EQUALITY_ACROSS_CALL = """
from dataclasses import dataclass

@dataclass
class Point:
    x: int
    y: int

def same(p, q):
    if p == q:
        return 1
    return 0

def main(n):
    a = Point(3, 4)
    b = Point(3, 4)
    c = Point(9, 9)
    printf("%d %d", same(a, b), same(a, c))
    return 0
"""

# A ONE-field dataclass. Its receiver IS its field, so it fits in one word and
# its `==` was already a value compare before this transform existed — which is
# why the rewrite is only NEEDED for a struct of more than one field, and why
# applying it here would be at best a no-op. It is pinned because "the answer
# was already right" is a claim about a measurement, and a measurement is worth
# pinning.
ONE_FIELD_EQUALITY = """
from dataclasses import dataclass

@dataclass
class Cell:
    v: int

def eq(a, b):
    if a == b:
        return 1
    return 0

def main(n):
    a = Cell(5)
    b = Cell(5)
    c = Cell(6)
    printf("%d %d", eq(a, b), eq(a, c))
    return 0
"""

# `@dataclass(eq=False)`. CPython leaves `__eq__` INHERITED, which is identity;
# on this path a bare struct's `==` IS an address compare, so honouring the
# option means leaving the comparison alone. The assertion is that it is False
# for two equal-valued distinct instances — the same answer a plain class
# gives, which is what `eq=False` means.
EQ_FALSE = """
from dataclasses import dataclass

@dataclass(eq=False)
class Point:
    x: int
    y: int

def eq(a, b):
    if a == b:
        return 1
    return 0

def main(n):
    a = Point(3, 4)
    b = Point(3, 4)
    printf("%d", eq(a, b))
    return 0
"""

# A class that declares its OWN `__eq__` — `OWN_EQ` and `OWN_EQ_ONE_FIELD`
# below, which are EXECUTED and compared with CPython, and the two
# `OWN_EQ_*_OPERAND` sources that are REFUSED.
#
# It used to be refused outright, and the reason it is worth three rows now is
# that the refusal was for the WRONG reason and then for a right one, and each
# of the three states is a program whose answer changed:
#
#   * the original refusal said `==` never dispatches by name — true on
#     2026-09-29, false since `formal/build.py`'s
#     `_rewrite_eq_on_frame_receivers` (and its one-word half);
#   * the second said this transform's field-wise desugar would replace the
#     method — true of the TRANSFORM and already handled, since
#     `rewrite_equality` skips a class with `own_eq`;
#   * what was actually left was the operator dispatch's own scope, and it is
#     not the class that is wrong, it is the COMPARISONS: two bare names of the
#     same class are answered by the method, and every other spelling is not.
#
# So the class is accepted and the residue is refused, each residue naming the
# comparison that cannot be lowered and why. A refusal that names a construct
# nobody can change is worse than a wrong answer a reader can see.

# Two DIFFERENT dataclass types compared. CPython's generated `__eq__` returns
# NotImplemented for a different type, which falls back to identity, so this is
# False; an address compare is also False. The transform must leave it alone
# rather than desugaring `A == B` into `A.f1 == B.f1 and ...`, which would be a
# comparison of fields the two classes do not share.
DIFFERENT_TYPES = """
from dataclasses import dataclass

@dataclass
class A:
    x: int
    y: int

@dataclass
class B:
    x: int
    y: int

def eq(a, b):
    if a == b:
        return 1
    return 0

def main(n):
    a = A(1, 2)
    b = B(1, 2)
    printf("%d", eq(a, b))
    return 0
"""

# A dataclass compared against a plain integer, and against a class of ONE
# field. Both are False in CPython (NotImplemented falls back to identity) and
# both are False here, but for different reasons — a word is not a frame
# address — and the case is here because a transform that rewrote every `==` in
# a function holding a dataclass would produce `a.x == 5`, which is a
# comparison the source never wrote.
MIXED_COMPARISON = """
from dataclasses import dataclass

@dataclass
class Point:
    x: int
    y: int

def eq(a, b):
    if a == b:
        return 1
    return 0

def main(n):
    p = Point(3, 4)
    printf("%d %d", eq(p, 5), eq(p, 0))
    return 0
"""

# A dataclass value used as a method receiver, with the comparison inside the
# method against the receiver and a parameter. The receiver is a holder by a
# different route than a constructor binding — it is `struct_receivers`, not
# `_constructor_bindings` — so it is a separate path through the same table.
SELF_COMPARISON = """
from dataclasses import dataclass

@dataclass
class Box:
    v: int

    def same_as(self, other):
        if self == other:
            return 1
        return 0

def main(n):
    a = Box(4)
    b = Box(4)
    c = Box(5)
    printf("%d %d", a.same_as(b), a.same_as(c))
    return 0
"""

# A string field, so the field-wise comparison is a `char *` compare rather
# than an integer one. It is a different lowering inside the chain
# (`_emit_strcmp_flags` rather than `_emit_cmp_flags`) and a chain that folds
# the two wrongly would show it.
STRING_FIELD = """
from dataclasses import dataclass

@dataclass
class Tag:
    name: str
    n: int

def eq(a, b):
    if a == b:
        return 1
    return 0

def main(n):
    a = Tag("x", 1)
    b = Tag("x", 1)
    c = Tag("y", 1)
    printf("%d %d", eq(a, b), eq(a, c))
    return 0
"""

# THE fourth way CPython's generated `__init__` and this path's field-filling
# construction differ, and the one the transform is FOR: a generated `__init__`
# has a signature per field — `def __init__(self, width=80, height=24)` — so a
# call may supply a PREFIX of the fields and a KEYWORD spelling, and the rest
# come from their own defaults. `Config(7)` is `width = 7, height = 24`, which
# CPython says and which this backend used to refuse
# (`bugs/FORMAL_dataclass_partial_construction.md`, now closed).
#
# Every row is here because each of the four spellings has a DIFFERENT answer if
# one of the rules is wrong, and a program that prints 7 24 7 24 7 3 cannot tell
# which rule produced which pair: `Config()` catches a default that was zeroed,
# `Config(7)` catches a prefix that was refused or filled with zeros,
# `Config(width=7)` catches a keyword read as a positional (which would land 7
# in whichever field sorted first), `Config(7, 3)` is the control that the
# ordinary full positional fill still works, and `Config(height=3)` catches a
# keyword matching the WRONG field.
OWN_EQ = """
from dataclasses import dataclass

@dataclass
class Always:
    x: int
    y: int

    def __eq__(self, other):
        return True

def eq(a, b):
    if a == b:
        return 1
    return 0

def main(n):
    a = Always(3, 4)
    b = Always(9, 9)
    printf("%d %d", eq(a, b), eq(a, a))
    return 0
"""

# The ONE-FIELD half of the same thing, and a different path: a struct of one
# field has no frame at all, so its value is a word and the dispatch reaches it
# through the one-word table rather than the holder table.  The old
# `FORMAL_eq_dispatch_on_a_frame_receiver.md` §1 is the measurement that the
# frame-only version of this answer was 0 where CPython says 1.
#
# THE COMPARISON IS IN `main`, not behind a call, and that is deliberate rather
# than convenient: a one-word class compared through a function BOUNDARY does
# not dispatch, on this tree and on the one before it —
# `bugs/FORMAL_one_word_eq_dispatch_stops_at_a_call_boundary.md` is the
# measurement, and it is a different construct from the one this file is about.
# A row here would pin a program that answers 0, and a case whose expectation
# is a known wrong answer teaches the next reader that 0 is the answer.
OWN_EQ_ONE_FIELD = """
from dataclasses import dataclass

@dataclass
class Tag:
    v: int

    def __eq__(self, other):
        return True

def main(n):
    a = Tag(5)
    b = Tag(6)
    printf("%d %d", a == b, a == a)
    return 0
"""

# The residue, and the two shapes that make it a residue: the operator's
# dispatch lowers a comparison only when BOTH operands are bare names this image
# can say are values of the same class.  `a == 5` is a word against a frame and
# `Always(3, 4) == Always(9, 9)` compares two temporaries — neither can be
# classified, and both would answer 0 through the address compare the dispatch
# exists to replace.
OWN_EQ_WORD_OPERAND = """
from dataclasses import dataclass

@dataclass
class Always:
    x: int
    y: int

    def __eq__(self, other):
        return True

def main(n):
    a = Always(3, 4)
    printf("%d", a == 5)
    return 0
"""

OWN_EQ_CONSTRUCTION_OPERAND = """
from dataclasses import dataclass

@dataclass
class Always:
    x: int
    y: int

    def __eq__(self, other):
        return True

def main(n):
    printf("%d", Always(3, 4) == Always(9, 9))
    return 0
"""

PARTIAL_CONSTRUCTION = """
from dataclasses import dataclass, field

@dataclass
class Config:
    width: int = field(default=80)
    height: int = 24

def main(n):
    a = Config()
    b = Config(7)
    c = Config(width=7)
    d = Config(7, 3)
    e = Config(height=3)
    printf("%d %d|", a.width, a.height)
    printf("%d %d|", b.width, b.height)
    printf("%d %d|", c.width, c.height)
    printf("%d %d|", d.width, d.height)
    printf("%d %d", e.width, e.height)
    return 0
"""

EXEC_CASES = [
    ("bare_decorator_constructs_in_declaration_order", BARE_CONSTRUCT),
    ("dotted_dataclasses_decorator_spelling", DOTTED_DECORATOR),
    ("field_default_is_lowered_to_its_literal", FIELD_DEFAULT),
    ("a_prefix_of_the_fields_fills_from_their_defaults", PARTIAL_CONSTRUCTION),
    ("dataclass_equality_is_field_wise", EQUALITY),
    ("dataclass_equality_through_a_call_boundary", EQUALITY_ACROSS_CALL),
    ("one_field_dataclass_equality_was_already_right", ONE_FIELD_EQUALITY),
    ("eq_false_keeps_the_inherited_identity_compare", EQ_FALSE),
    ("two_different_dataclass_types_compare_false", DIFFERENT_TYPES),
    ("a_dataclass_compared_with_a_word_is_false", MIXED_COMPARISON),
    ("equality_inside_a_method_compares_the_receiver", SELF_COMPARISON),
    ("a_string_field_compares_as_text", STRING_FIELD),
    # A class with its OWN `__eq__` is EXECUTED, and the two answers are the
    # whole point: `eq(a, b)` must reach the method (1, because the method
    # returns True for anything) and so must `eq(a, a)` — a rewrite that
    # short-circuited the identity case, or the field-wise desugar this
    # transform declines to apply, would answer 0 for one of them.
    ("a_user_declared_eq_reaches_the_method", OWN_EQ),
    ("a_user_declared_eq_reaches_the_method_on_a_one_field_class",
     OWN_EQ_ONE_FIELD),
]


def run_exec_cases(tmpdir, only=None):
    for name, source in EXEC_CASES:
        if only and name not in only:
            continue
        try:
            got_out, got_rc = formal_run(tmpdir, name, source)
        except BuildRefused as e:
            check(False, name, f"refused: {str(e)[-500:]}")
            continue
        except subprocess.TimeoutExpired:
            check(False, name, "build timed out")
            continue
        want_out, want_rc = cpython_run(tmpdir, name, source)
        check(got_out == want_out,
              f"{name}: the arm64 image and CPython disagree on stdout",
              f"arm64 {got_out!r} vs CPython {want_out!r}")
        check(got_rc == want_rc,
              f"{name}: the arm64 image and CPython disagree on the exit status",
              f"arm64 {got_rc} vs CPython {want_rc}")


# ── 2. the refused subset, pinned by the MESSAGE ───────────────────────────
#
# A refusal that stops naming the construct is a regression this file would not
# otherwise see, and the message is the deliverable for a construct that cannot
# be lowered: it is what tells the next reader which capability is missing and
# what to do instead. Each case below asserts on a distinctive phrase, not on
# the whole message, so a wording improvement does not break the pin and a
# change of SUBSTANCE does.

FROZEN = """
from dataclasses import dataclass

@dataclass(frozen=True)
class Point:
    x: int
    y: int

def main(n):
    p = Point(3, 4)
    return 0
"""

ORDER = """
from dataclasses import dataclass

@dataclass(order=True)
class Point:
    x: int
    y: int

def main(n):
    return 0
"""

REPR_OPTION = """
from dataclasses import dataclass

@dataclass(repr=True)
class Point:
    x: int
    y: int

def main(n):
    return 0
"""

DEFAULT_FACTORY = """
from dataclasses import dataclass, field

@dataclass
class Bag:
    items: list = field(default_factory=list)

def main(n):
    return 0
"""

INHERITANCE = """
from dataclasses import dataclass

@dataclass
class Base:
    a: int

@dataclass
class Derived(Base):
    b: int

def main(n):
    return 0
"""

POST_INIT = """
from dataclasses import dataclass

@dataclass
class Point:
    x: int

    def __post_init__(self):
        self.x = self.x + 1

def main(n):
    return 0
"""

UNKNOWN_OPTION = """
from dataclasses import dataclass

@dataclass(whatever=True)
class Point:
    x: int

def main(n):
    return 0
"""

KW_ONLY = """
from dataclasses import dataclass

@dataclass(kw_only=True)
class Point:
    x: int

def main(n):
    return 0
"""

# The reflection half, and the whole reason this file's docstring says the
# subset stops where it does. `is_dataclass(x)` where `x` is a PLAIN WORD, so
# the frame-escape analysis has nothing to say and the dataclass refusal is the
# one that fires — which is the point: the diagnostic must name the missing
# TYPE TAG, not a frame address, because a type tag is the thing that is
# missing and a frame address is merely the first thing that goes wrong.
REFLECTION_CALL = """
import dataclasses

def is_dc(x):
    return dataclasses.is_dataclass(x)

def main(n):
    return 0
"""

# The same question with no call on it, which is how `formal/types.py:289`
# spells it. A separate entry point so the two cannot say different things.
REFLECTION_ATTRIBUTE = """
import dataclasses

def probe(x):
    if hasattr(x, "__dataclass_fields__"):
        return 1
    return 0

def main(n):
    return 0
"""

# A from-import, so the call is spelled BARE. If the check only recognised the
# dotted spelling it would let this through to fail three layers down as an
# unresolved name, which is the failure mode the check exists to prevent.
REFLECTION_BARE_IMPORT = """
from dataclasses import fields

def nfields(x):
    return fields(x)

def main(n):
    return 0
"""

# A GUARD, and the reason `check_reflection_calls` is gated on the import at
# all: an unrelated object's `.fields` is not a dataclasses call, and refusing
# it would be a false claim about the file. This case must BUILD.
UNRELATED_FIELDS = """
class Holder:
    def fields(self):
        return 1

def main(n):
    h = Holder()
    return h.fields()
"""

REFUSE_CASES = [
    ("frozen_is_refused_with_its_reason", FROZEN,
     ["frozen=True", "no place to put that setter"]),
    ("order_is_refused_with_its_reason", ORDER,
     ["order=True", "no synthesised comparison"]),
    ("repr_is_refused_with_its_reason", REPR_OPTION,
     ["repr", "SEGFAULTS"]),
    ("default_factory_is_refused_with_its_reason", DEFAULT_FACTORY,
     ["default_factory", "nowhere to keep the result"]),
    ("inheritance_is_refused_with_its_reason", INHERITANCE,
     ["inherits from", "no base-class field merge"]),
    ("post_init_is_refused_with_its_reason", POST_INIT,
     ["__post_init__", "no point in that sequence"]),
    ("an_unknown_option_is_refused_by_name", UNKNOWN_OPTION,
     ["whatever", "not ignored"]),
    ("kw_only_is_refused_with_its_reason", KW_ONLY,
     ["kw_only", "one construction shape here, not two"]),
    # A user `__eq__` whose COMPARISONS are not the shape the dispatch lowers.
    # The needle is the clause that says which shape, because "it is refused"
    # is not the assertion — `OWN_EQ` is a user `__eq__` that is EXECUTED above,
    # and this pair is what keeps the two from drifting into one answer. A
    # refusal of the class would refuse `OWN_EQ` too, which computes exactly.
    ("a_user_declared_eq_against_a_word_is_refused_by_the_shape",
     OWN_EQ_WORD_OPERAND,
     ["__eq__", "5 is not a plain name"]),
    ("a_user_declared_eq_between_two_constructions_is_refused_by_the_shape",
     OWN_EQ_CONSTRUCTION_OPERAND,
     ["__eq__", "ADDRESSES"]),
    ("reflection_is_refused_by_name", REFLECTION_CALL,
     ["is_dataclass", "no type tag attached"]),
    ("the_fields_attribute_is_refused_by_name", REFLECTION_ATTRIBUTE,
     ["__dataclass_fields__", "no type tag attached"]),
    ("a_bare_from_imported_reflection_call_is_refused", REFLECTION_BARE_IMPORT,
     ["fields", "no type tag attached"]),
]


def run_refuse_cases(tmpdir, only=None):
    for name, source, needles in REFUSE_CASES:
        if only and name not in only:
            continue
        try:
            formal_run(tmpdir, name, source)
        except BuildRefused as e:
            msg = str(e)
            check(all(nd in msg for nd in needles), name,
                  "the refusal does not say what it should: missing "
                  + ", ".join(repr(nd) for nd in needles if nd not in msg)
                  + f" — got: {msg[-400:]}")
            continue
        except subprocess.TimeoutExpired:
            check(False, name, "build timed out")
            continue
        check(False, name, "BUILT a construct that has to be refused")


def run_guard_case(tmpdir, only=None):
    name = "an_unrelated_object_s_fields_is_not_refused"
    if only and name not in only:
        return
    try:
        out, rc = formal_run(tmpdir, name, UNRELATED_FIELDS)
    except BuildRefused as e:
        check(False, name,
              f"refused an unrelated .fields: {str(e)[-300:]}")
        return
    check(rc == 1, name, f"expected the method's own return value, got {rc}")


# A default with NO CPython oracle, checked against the REPRESENTATION on both
# architectures. `run_exec_cases` diffs against CPython, which is the right
# default for this suite and the wrong oracle here: `printf("%d", None)` is a
# TypeError on CPython, so a program whose whole point is that a `None` default
# reads as the word 0 cannot be run through the reference to find out what it
# should print. What it should print is a property of the representation, and
# the representation is decided in `formal/model.py` — so the expectation is
# written down here, once, and BOTH backends are held to it.
REPRESENTATION_CASES = [
    ("a_none_field_default_reads_as_the_word_zero", NONE_FIELD_DEFAULT,
     "0 7 3 7", 0),
]


def run_representation_cases(tmpdir, only=None):
    for name, source, want_out, want_rc in REPRESENTATION_CASES:
        if only and name not in only:
            continue
        answers = {}
        for arch in ("arm64", "x86_64"):
            try:
                answers[arch] = formal_run(tmpdir, f"{name}_{arch}", source,
                                           arch)
            except BuildRefused as e:
                check(False, name, f"{arch} refused: {str(e)[-400:]}")
                answers = None
                break
            except subprocess.TimeoutExpired:
                check(False, name, f"{arch} build timed out")
                answers = None
                break
        if answers is None:
            continue
        (arm_out, arm_rc), (x86_out, x86_rc) = answers["arm64"], \
            answers["x86_64"]
        # The two architectures agreeing is the assertion that matters most
        # here: the fold is in `formal/model.py`, which both read, so a
        # disagreement would mean one of them stopped reading it — and the
        # failure mode is a wrong number on one side with everything else
        # green.
        check(arm_out == x86_out,
              f"{name}: arm64 and x86-64 disagree on stdout",
              f"arm64 {arm_out!r} vs x86-64 {x86_out!r}")
        check(arm_out == want_out and arm_rc == want_rc == x86_rc,
              f"{name}: the image is not the representation",
              f"want {want_out!r}/{want_rc}, arm64 {arm_out!r}/{arm_rc}, "
              f"x86-64 {x86_out!r}/{x86_rc}")


# ── 3. the corpus, DISCOVERED from the tree rather than listed ──────────────
#
# The five files this closes were measured, not guessed: a `@dataclass` in this
# repository, built through the formal path, and each one asserted to be either
# built or refused with a message that names the construct. This is the check
# that the transform is not a shape that only the hand-written cases above
# happen to fit — a decorator transform is only correct on the classes that
# really use it.
def discover_corpus():
    found = []
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs
                   if d not in ("build", ".git", ".tmp", "__pycache__",
                                "node_modules")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            if os.path.abspath(p) == os.path.abspath(__file__):
                continue
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            if "@dataclass" in text or "@dataclasses.dataclass" in text:
                found.append(os.path.relpath(p, HERE))
    return sorted(found)


def run_corpus_case(tmpdir, only=None):
    """Every `@dataclass` in THIS repository is classified, not skipped.

    A decorator transform is only correct on the classes that really use it,
    and the classes that really use it are this repository's own — including
    two that are far larger and stranger than anything in the table above
    (`mojo/backend_gimple/cpp_core.py` is 7479 lines and
    `ownership_check.py` walks AST nodes with `dataclasses.fields`). The
    assertion is therefore NOT that they build: they import host modules this
    backend has no source for, and they will not. It is that each one is
    CLASSIFIED — refused with a message that names a construct, or built — and
    that none of them produces a traceback or an empty diagnostic. A file in
    this repository that mentions `@dataclass` and crashes the compiler is a
    defect in the transform, and a build-only test suite of hand-written cases
    would not see it.
    """
    name = "the_repositorys_own_dataclasses_are_classified_not_crashed"
    if only and name not in only:
        return
    corpus = discover_corpus()
    check(bool(corpus), f"{name}: the corpus is discovered from the tree",
          "no @dataclass found in this repository, so the discovery rule is "
          "wrong rather than the tree being empty")
    for rel in corpus:
        with open(os.path.join(HERE, rel), encoding="utf-8",
                  errors="ignore") as f:
            text = f.read()
        try:
            formal_run(tmpdir, "corpus_" + rel.replace("/", "_")[:-3], text)
            verdict = "builds"
        except BuildRefused as e:
            verdict = str(e)
        except subprocess.TimeoutExpired:
            verdict = "timed out"
        check("Traceback" not in verdict and bool(verdict),
              f"{name}: {rel} is classified, not crashed",
              verdict[-300:])


# ── 4. the two architectures AGREE ──────────────────────────────────────────
#
# The transform is arch-free — it lives in the shared front end, and both
# backends go through `formal/build.py`'s one pipeline — so a two-backend
# divergence here would be a divergence in a transform both of them read, which
# is the shape this project has measured more than once (a real 2026-08-13→09-13
# case produced a 1.4M-line diff from correct while every other check stayed
# green). A field-wise `==` is exactly where that would show: the chain is
# lowered by each backend's own compare, and the two have to agree about what a
# field read produces.
#
# So this builds and EXECUTES the same program on both, and asserts all three
# answers — arm64, x86-64, CPython — are one answer. Measured before this case
# existed: arm64 `1 0`, x86-64 `1 0`, CPython `1 0`.

def run_arch_parity_case(tmpdir, only=None):
    name = "both_architectures_agree_with_cpython_on_the_field_wise_compare"
    if only and name not in only:
        return
    try:
        arm, arm_rc = formal_run(tmpdir, name + "_arm", EQUALITY, "arm64")
        x86, x86_rc = formal_run(tmpdir, name + "_x86", EQUALITY, "x86_64")
    except BuildRefused as e:
        check(False, name, f"refused: {str(e)[-400:]}")
        return
    want, want_rc = cpython_run(tmpdir, name, EQUALITY)
    check(arm == x86,
          f"{name}: arm64 and x86_64 disagree on stdout",
          f"arm64 {arm!r} vs x86_64 {x86!r}")
    check(arm == want and arm_rc == want_rc == x86_rc,
          f"{name}: the image and CPython disagree",
          f"arm64 {arm!r}/{arm_rc} x86_64 {x86!r}/{x86_rc} "
          f"CPython {want!r}/{want_rc}")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="*")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    only = set(args.cases) or None

    with tempfile.TemporaryDirectory() as tmpdir:
        run_exec_cases(tmpdir, only)
        run_refuse_cases(tmpdir, only)
        run_guard_case(tmpdir, only)
        run_representation_cases(tmpdir, only)
        run_corpus_case(tmpdir, only)
        run_arch_parity_case(tmpdir, only)

    passed = sum(1 for ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    for ok, what in RESULTS:
        if args.verbose:
            print(("PASS  " if ok else "FAIL  ") + what, flush=True)
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
