#!/usr/bin/env python3
"""test_namedtuple_formal.py -- `typing.NamedTuple` on the formal backend, as
CPython's, on BOTH architectures, with the refusals pinned by their MESSAGE.

**The oracle is CPython, on the same text.** Every execution case is run THREE
times: `python3` on the source, an arm64 image, and an x86-64 image, and all
three must agree on stdout AND exit status. Not "it built" and not a
hand-written expected number — the numbers in the comments are there to be read
against, and the assertion is the comparison.

**Why this file exists and why it is not part of `test_dataclasses_formal.py`.**
That file's docstring scopes it to the `@dataclass` DECORATOR, and a
`typing.NamedTuple` is a different value type that reaches the backend by a
different door: no decorator, a `NamedTuple` in the class's `bases`. The
comparison machinery they share is real — `formal/dataclass_transform.py`'s
`rewrite_equality` desugars both, because a namedtuple's `==` and a dataclass's
`==` are the same chain over the same fields in the same order — but the
*recognition* is separate and the two classes of program are separate, and a
file whose docstring says `@dataclass` should not be the file that pins
`class P(NamedTuple)`.

**What was wrong, measured, before this file existed.** A namedtuple on this
path is a struct, and a struct of more than one field is the ADDRESS of a frame
of 8-byte slots. Every comparison operator therefore reached a compare of two
addresses, with no refusal and no message:

    class P(NamedTuple):
        x: int
        y: int
    def eq(a, b):
        if a == b: return 1
        return 0
    eq(P(1, 2), P(1, 2))     ->  0     on BOTH architectures, exit 0

CPython answers 1. `namedtuple_equality_is_field_wise` and
`namedtuple_ordering_is_lexicographic` are those measurements; they are the
first two rows because a silent wrong `==` is the outcome this backend exists
to prevent, and it was the state of the whole type.

**What is NOT here, and is refused rather than pretended at.** `p[0]`, `len(p)`,
`a, b = p`, `for v in p`, `p._replace(...)`, `p._asdict()` and `repr(p)` are all
tuple operations on a value that has no tuple reading on this path. Each is
pinned by the refusal that names it, and `FORMAL value types beyond comparison`
records the whole table with the next step for each. A refusal here is the
honest answer; what is refused is not implemented, and the word "implemented"
is doing no work it has not earned.

Run:  python3 test_namedtuple_formal.py [-v] [case ...]
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

# The CPython side of the comparison, and the reason `printf` is spelled the way
# it is: it is this backend's own output primitive (`formal/arm64_codegen.py`
# lowers it to a libSystem call), so the oracle needs the same spelling and a
# difference in the output is a difference in the COMPUTATION rather than in the
# printing.
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
    # The source file's NAME does not carry the architecture, and that is load
    # bearing rather than tidiness: a refusal quotes the file it is about
    # (`u.py imports 'collections', …`), so a per-architecture filename would
    # make every message differ between the two backends for a reason that has
    # nothing to do with them — and `run_both_architectures_say_the_same_thing`
    # below compares them verbatim. The BINARY is per-architecture, which is
    # what has to differ.
    path = os.path.join(tmpdir, name + ".src.py")
    with open(path, "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, f"{name}.{arch}.bin")
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


# ── 1. the comparison: built, EXECUTED, compared with CPython ───────────────
#
# THE case, and it was a silent wrong answer before
# `formal/dataclass_transform.py`'s `rewrite_equality` was pointed at the
# `NamedTuple` table. `P(1, 2) == P(1, 2)` compares two FRAME ADDRESSES, and two
# constructions are two objects, so the answer was 0 on both architectures with
# nothing on stderr where CPython says 1.
NAMEDTUPLE_EQUALITY = """
from typing import NamedTuple

class P(NamedTuple):
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
    p = P(1, 2)
    q = P(1, 2)
    r = P(1, 3)
    printf("%d %d %d %d", eq(p, q), eq(p, r), ne(p, q), ne(p, r))
"""

# The same through a FUNCTION BOUNDARY with the operands as PARAMETERS, because
# that is where the holder analysis has to have run: a name is a namedtuple
# value only because some call site passed one to it, so a rewrite that read
# only constructor bindings would desugar this caller and leave this one
# comparing addresses — and the two halves of one program would then disagree.
NAMEDTUPLE_EQUALITY_ACROSS_CALL = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

def same(a, b):
    if a == b:
        return 1
    return 0

def main(n):
    a = P(1, 2)
    b = P(1, 2)
    c = P(9, 9)
    printf("%d %d", same(a, b), same(a, c))
"""

# A CONSTRUCTION as one operand, which is the shape that had no answer at all:
# `p == P(1, 2)` is a field-wise comparison CPython can answer, and the rewrite
# needs the construction bound to a local first because a field read is
# `base + 8·slot` over a NAME (`formal/build.py`'s
# `_hoist_value_type_construction_operands`). Measured before it: 0 on both
# architectures where CPython says 1.
NAMEDTUPLE_EQUALITY_WITH_A_CONSTRUCTION_OPERAND = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

def main(n):
    p = P(1, 2)
    printf("%d %d %d", 1 if p == P(1, 2) else 0,
           1 if p == P(2, 2) else 0, 1 if p != P(2, 2) else 0)
"""

# LEXICOGRAPHIC ordering, and the reason a namedtuple's `<` is not a dataclass's.
# `tuple.__lt__` is "the first differing element decides", so for `x, y`:
# `a.x < b.x or (a.x == b.x and a.y < b.y)` — where a `@dataclass`'s ordering
# would be a conjunction of per-field comparisons. `comparison_chain` builds the
# conjunction and `lexicographic_chain` builds this, and the difference is
# visible in the second field: `P(1, 9) < P(2, 0)` is True by `x` alone, while
# `P(1, 2) < P(1, 3)` needs the tie on `x` to defer to `y`.
#
# All four operators, because `<=`/`>`/`>=` are DERIVED from `<` (CPython's own
# definition of `tuple`: `a <= b` is `a < b or a == b`, `a > b` is `b < a`) and a
# rewrite that got three of the four right would be three wrong answers.
NAMEDTUPLE_ORDERING = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

def lt(a, b):
    if a < b:
        return 1
    return 0

def le(a, b):
    if a <= b:
        return 1
    return 0

def gt(a, b):
    if a > b:
        return 1
    return 0

def ge(a, b):
    if a >= b:
        return 1
    return 0

def main(n):
    a = P(1, 2)
    b = P(1, 3)
    c = P(2, 0)
    printf("%d %d %d %d", lt(a, b), le(a, a), gt(c, a), ge(a, a))
"""

# The `x`-alone case, which is the row that distinguishes LEXICOGRAPHIC from a
# per-field conjunction: `P(1, 9) < P(2, 0)` is True on `x` and False on `y`, so
# a conjunction would say False. CPython agrees it is True.
NAMEDTUPLE_ORDERING_FIRST_FIELD_DECIDES = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

def main(n):
    a = P(1, 9)
    b = P(2, 0)
    printf("%d %d", 1 if a < b else 0, 1 if b < a else 0)
"""

# A THREE-field namedtuple, so the chain's accumulation is exercised at a depth
# where an off-by-one in the tie prefix shows: `P(1, 1, 5) < P(1, 1, 6)` needs
# TWO ties before it reaches `z`.
NAMEDTUPLE_THREE_FIELDS = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int
    z: int

def main(n):
    a = P(1, 1, 5)
    b = P(1, 1, 6)
    c = P(1, 2, 0)
    printf("%d %d %d", 1 if a < b else 0, 1 if a < c else 0, 1 if a == P(1,1,5) else 0)
"""

# A namedtuple declaring its OWN `__eq__`, which must win over the chain: CPython
# keeps a user-declared dunder in preference to the generated one, and
# `own_eq` in the table is what the rewrite consults. The method returns True for
# everything, so the answer is 1 where the field chain would say 0.
NAMEDTUPLE_OWN_EQ_WINS = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

    def __eq__(self, other):
        return True

def main(n):
    a = P(1, 2)
    b = P(9, 9)
    printf("%d %d", 1 if a == b else 0, 1 if a == a else 0)
"""

# DEFAULTS, which is the half that already worked (a namedtuple's field default
# is a class-level constant and this path folds those) and is pinned because
# "the answer was already right" is a claim about a measurement, and a
# measurement is worth pinning. `P()` and `P(1)` are both spellings CPython
# accepts when every field after the first has a default.
NAMEDTUPLE_DEFAULTS = """
from typing import NamedTuple

class P(NamedTuple):
    x: int = 5
    y: int = 6

def main(n):
    p = P()
    q = P(1)
    printf("%d %d %d %d", p.x, p.y, q.x, q.y)
"""

# The field READS, which are the other half that already worked: a namedtuple's
# attributes are its fields and a field read is a load at `base + 8·slot`, which
# is what this backend has always emitted. It is the baseline the comparison
# rows above are measured against — if the fields were not readable, the chain
# over them would not lower either.
NAMEDTUPLE_FIELD_READS = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

def main(n):
    p = P(3, 4)
    printf("%d %d", p.x, p.y)
"""

EXEC_CASES = [
    ("namedtuple_equality_is_field_wise", NAMEDTUPLE_EQUALITY),
    ("namedtuple_equality_through_a_call_boundary",
     NAMEDTUPLE_EQUALITY_ACROSS_CALL),
    ("namedtuple_equality_with_a_construction_operand",
     NAMEDTUPLE_EQUALITY_WITH_A_CONSTRUCTION_OPERAND),
    ("namedtuple_ordering_is_lexicographic", NAMEDTUPLE_ORDERING),
    ("namedtuple_ordering_first_field_decides",
     NAMEDTUPLE_ORDERING_FIRST_FIELD_DECIDES),
    ("namedtuple_three_fields", NAMEDTUPLE_THREE_FIELDS),
    ("a_namedtuples_own_eq_wins_over_the_chain", NAMEDTUPLE_OWN_EQ_WINS),
    ("namedtuple_defaults_still_read_their_literals", NAMEDTUPLE_DEFAULTS),
    ("namedtuple_field_reads", NAMEDTUPLE_FIELD_READS),
]


# ── 2. the refused subset, pinned by the MESSAGE ────────────────────────────
#
# The other tuple operations. Each is refused BY NAME with a message that says
# what is missing, and pinning the message is the assertion: a refusal that
# stops naming its construct is a regression nothing else here would see.
#
# The one that is not a plain refusal is the UNPACK, and it is the row worth
# reading: it used to BUILD on both architectures and answer
# `a=<second field> b=<past the end of the frame>`, or exit 1 printing nothing
# when the first field's value happened not to match the target count — so
# whether a program ran at all was decided by a field's value. That is the
# measurement `formal/model.py`'s `frame_unpack_operand_refusal` records.
NAMEDTUPLE_UNPACK = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

def main(n):
    p = P(1, 2)
    a, b = p
    printf("%d %d", a, b)
"""

NAMEDTUPLE_INDEX = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

def main(n):
    p = P(1, 2)
    printf("%d %d", p[0], p[1])
"""

NAMEDTUPLE_LEN = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

def main(n):
    printf("%d", len(P(1, 2)))
"""

NAMEDTUPLE_ITERATION = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

def main(n):
    t = 0
    for v in P(1, 2):
        t = t + v
    printf("%d", t)
"""

NAMEDTUPLE_REPLACE = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

def main(n):
    q = P(1, 2)._replace(x=9)
    printf("%d %d", q.x, q.y)
"""

NAMEDTUPLE_ASDICT = """
from typing import NamedTuple

class P(NamedTuple):
    x: int
    y: int

def main(n):
    d = P(1, 2)._asdict()
    printf("%d %d", d["x"], d["y"])
"""

# `collections.namedtuple`, which is the same value type with the fields written
# at the CALL rather than in a class body. This path has no class body to read a
# field list from, so the whole construct is out of reach — and the honest
# answer is a refusal that says so rather than a `collections` module exporting a
# function that could not build one. The docstring of
# `formal/dataclass_transform.is_namedtuple_struct` names this spelling as the
# reason the base-name recognition exists at all.
NAMEDTUPLE_COLLECTIONS = """
import collections

P = collections.namedtuple("P", ["x", "y"])

def main(n):
    p = P(1, 2)
    printf("%d %d", p.x, p.y)
"""

REFUSE_CASES = [
    # The fifth member of the container family, and the one that used to answer
    # `a=2 b=<garbage>` on arm64 and a DIFFERENT garbage on x86-64. The needle is
    # the ARITY clause rather than the general one because that is what is
    # actually wrong about a tuple unpack of a frame — the blob unpack reads
    # offset 0 as a count and a frame's offset 0 is its first FIELD.
    ("a_namedtuple_cannot_be_unpacked", NAMEDTUPLE_UNPACK,
     ["right-hand side of a tuple assignment", "FRAME ADDRESS"]),
    ("a_namedtuple_cannot_be_indexed", NAMEDTUPLE_INDEX,
     ["CONTAINER operation on a P FRAME ADDRESS"]),
    ("a_namedtuple_has_no_length", NAMEDTUPLE_LEN,
     ["len("]),
    ("a_namedtuple_cannot_be_iterated", NAMEDTUPLE_ITERATION,
     ["CONTAINER operation on a P FRAME ADDRESS"]),
    ("_replace_is_not_a_method_call_on_a_value", NAMEDTUPLE_REPLACE,
     ["_replace() is a method call on a value"]),
    ("_asdict_is_not_a_method_call_on_a_value", NAMEDTUPLE_ASDICT,
     ["_asdict() is a method call on a value"]),
    ("collections_namedtuple_is_a_call_and_not_a_class_body",
     NAMEDTUPLE_COLLECTIONS,
     ["collections"]),
]


def run_exec_cases(tmpdir, only=None):
    for name, source in EXEC_CASES:
        if only and name not in only:
            continue
        answers = {}
        ok = True
        for arch in ("arm64", "x86_64"):
            try:
                answers[arch] = formal_run(tmpdir, f"{name}_{arch}", source,
                                           arch)
            except BuildRefused as e:
                check(False, name, f"{arch} refused: {str(e)[-500:]}")
                ok = False
                break
            except subprocess.TimeoutExpired:
                check(False, name, f"{arch} build timed out")
                ok = False
                break
        if not ok:
            continue
        want_out, want_rc = cpython_run(tmpdir, name, source)
        for arch in ("arm64", "x86_64"):
            got_out, got_rc = answers[arch]
            check(got_out == want_out,
                  f"{name}: the {arch} image and CPython disagree on stdout",
                  f"{arch} {got_out!r} vs CPython {want_out!r}")
            check(got_rc == want_rc,
                  f"{name}: the {arch} image and CPython disagree on the exit "
                  f"status", f"{arch} {got_rc} vs CPython {want_rc}")


def run_refuse_cases(tmpdir, only=None):
    for row in REFUSE_CASES:
        name, source, needles = row[0], row[1], row[2]
        if only and name not in only:
            continue
        for arch in ("arm64", "x86_64"):
            try:
                out, rc = formal_run(tmpdir, f"{name}_{arch}", source, arch)
            except BuildRefused as e:
                msg = str(e)
                # Both architectures must refuse, and must say the SAME thing:
                # the message is shared text (`formal/model.py`), so a
                # disagreement here means one backend stopped reading it.
                check(all(n in msg for n in needles),
                      f"{name}: the {arch} refusal does not say why",
                      f"want {needles!r} in {msg[-300:]!r}")
                continue
            except subprocess.TimeoutExpired:
                check(False, name, f"{arch} build timed out")
                continue
            check(False, name,
                  f"{arch} BUILT it ({out!r}/{rc}) where CPython's answer is a "
                  f"different program")


def run_both_architectures_say_the_same_thing(tmpdir, only=None):
    """Every refusal above, with the two architectures' messages COMPARED.

    A separate pass rather than a clause in the loop above because the loop only
    runs the second build when the first refused, so a divergence is exactly the
    case it cannot see: one architecture refusing and the other building is two
    FAIL rows in that loop, but a divergence in the WORDING is none. The message
    is shared text in `formal/model.py`, so this is the assertion that both
    emitters are still asking the same function.
    """
    for row in REFUSE_CASES:
        name, source = row[0], row[1]
        if only and name not in only:
            continue
        messages = {}
        # The SAME `name` for both, which is what makes the comparison a fact
        # about the two backends rather than about the two filenames: a refusal
        # quotes the file it is about, so a per-architecture name would make
        # every message differ for a reason that has nothing to do with them.
        for arch in ("arm64", "x86_64"):
            try:
                formal_run(tmpdir, f"{name}_parity", source, arch)
            except BuildRefused as e:
                messages[arch] = str(e)
            except subprocess.TimeoutExpired:
                messages[arch] = "TIMEOUT"
        check(len(messages) == 2 and messages.get("arm64") == messages.get("x86_64"),
              f"{name}: the two architectures do not say the same thing",
              f"arm64 {messages.get('arm64', '')[-200:]!r} vs "
              f"x86-64 {messages.get('x86_64', '')[-200:]!r}")


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="*")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    only = set(args.cases) or None

    with tempfile.TemporaryDirectory() as tmpdir:
        run_exec_cases(tmpdir, only)
        run_refuse_cases(tmpdir, only)
        run_both_architectures_say_the_same_thing(tmpdir, only)

    passed = sum(1 for ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    for ok, what in RESULTS:
        if args.verbose:
            print(("PASS  " if ok else "FAIL  ") + what, flush=True)
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))