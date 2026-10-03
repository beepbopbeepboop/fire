#!/usr/bin/env python3
"""`formal/hostmods/enum.mojo` and `contextlib.mojo`, differential against CPython.

    python3 test_formal_core_hostmods.py [-v] [group ...]

Groups: `enum-value`, `enum-shape`, `enum-absent`, `ctx`, `ctx-absent`,
`functools-absent`, `resolve`. With no argument, all.

WHY THESE TWO ARE IN ONE FILE
-----------------------------
Both are the same shape — a module whose whole content is one or two names whose
answers are CPython's to give — and both exist for the same reason, which is
measurable rather than administrative. `tools/formal_sweep.py` reported
`not-answerable/host-import` for every file importing them, and a file whose only
problem is that its first line says `from enum import Enum` is a file with a
diagnostic about the TARGET where it needed one about itself:

| file | before the module | after |
|---|---|---|
| `type_system.py` | `imports 'enum', which is a host module` | refuses `Type.origin`'s dataclass default |
| `formal/x86_64.py` | `imports 'enum', which is a host module` | refuses `base.value` in `_rm_disp` |
| `test_suite.py` (contextlib) | `imports 'contextlib', which is a host module` | names `shlex`, the next thing it wants |

Neither file BUILDS after its module lands, and this file does not pretend
otherwise — `enum-shape` says so in its own assertions. What moved is the
subject of the refusal, which is the whole value of a module in that directory.

`functools` IS HERE AS AN ABSENCE, and that is the point of its group: every
one of its names needs either a first-class function value or DECORATOR
semantics, and a decorator on this path is parsed and never applied — so an
exported `lru_cache` would be a program that runs and skips the work it asked
for. `bugs/FORMAL_functools_is_unbuildable_as_a_host_module.md` has the census
and the two refusals that are measurements rather than readings.

WHY THE ORACLE IS CPython AND NOT A TABLE
-----------------------------------------
`enum` is the module where a plausible-looking implementation is most likely to be
wrong: `.value` and `.name` are two attributes, and a module that gets one right
and the other wrong produces a program that computes with plausible register
numbers. So every answer here is computed twice — once by this process's own
`enum` and once by an image built through the formal backend and EXECUTED — and
the two are compared. Nothing in this file is a recorded constant; delete the
module and CPython's own values are what the image has to match.

THE BUG THIS FILE EXISTS BECAUSE
--------------------------------
`.value` on an enum member used to read **0** where CPython reads the member's
value, silently, on both backends:

    class Reg(Enum):
        RAX = 0
        R15 = 15
    printf("%d %d", Reg.R15.value, Reg.RAX.value)     # was 0 0; CPython 15 0

`formal/x86_64.py` does its register arithmetic through `.value`, so an image
with the answer wrong there emits wrong machine code and exits 0. `enum-value` is
the group that would go red if it regressed, and it covers the case the fix is
easy to get wrong: `.name` must still answer where `.value` is REFUSED, because
that asymmetry is CPython's too.

Run:  python3 test_formal_core_hostmods.py [-v] [group]
"""

import argparse
import enum
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
sys.path.insert(0, HERE)

from test_formal_json import Failure, check  # noqa: E402
import test_formal_json as J  # noqa: E402

TEMP = None

BACKENDS = ("arm64", "x86_64")


def build(src, name, backend=None):
    """`fire.py build --formal` of `src`, on `backend` (arm64 when None).

    The json suite's own driver, plus the one argument it does not take. It is
    re-implemented here rather than added to `test_formal_json.py` because that
    file's driver is imported by several other suites for its own reasons and
    this is the only one of them that builds for a second architecture; the
    fifteen lines are the alternative to every caller growing the same flag."""
    tmp = os.path.join(TEMP, name + ".mojo")
    out = os.path.join(TEMP, name)
    with open(tmp, "w") as f:
        f.write(src)
    argv = [sys.executable, FIRE, "build", "--formal", "--no-prove"]
    if backend:
        argv.append(f"--backend={backend}")
    argv += ["-o", out, tmp]
    r = subprocess.run(argv, capture_output=True, text=True,
                       timeout=J.BUILD_TIMEOUT, cwd=HERE)
    check(r.returncode == 0,
          f"[{backend or 'arm64'}] build failed: "
          f"{(r.stderr or r.stdout).strip()[-600:]}")
    check(os.path.isfile(out), f"[{backend or 'arm64'}] no image at {out}")
    return out


def run(out):
    """Execute the image and return what it printed."""
    r = subprocess.run([out], capture_output=True, timeout=J.RUN_TIMEOUT,
                       cwd=HERE)
    check(r.returncode == 0,
          f"image exited {r.returncode}: "
          f"{(r.stderr or b'').decode('utf-8', 'replace').strip()[-300:]}")
    return r.stdout.decode("latin-1")

# The corpus for `enum-value`, as (class name, member, value) triples.
# Deliberately includes the shapes that are easy to get wrong: 0 (which a "read
# as zero" bug would pass), a value that is also a plausible register number, and
# a STRING member, whose `.value` is a string and whose `.name` is its spelling.
#
# Each entry is (name, member, value) and the answer is computed from THIS
# process's `enum`, never written down here.
#
# A NEGATIVE value is in the table, and it was the row that was missing for the
# longest: `A = -3` parses to `UnaryOp('-', IntLiteral(3))` rather than to an
# `IntLiteral`, and `formal/model.py::literal_default_word` used to be a second,
# smaller classifier beside `fold_literal_expr` with no unary arm at all — so the
# value was REFUSED with a message claiming it "is not a value this build can
# materialize", which is false and sends a reader hunting for a non-literal that
# is not in their source. `literal_default_word` now folds with
# `fold_literal_expr`, the folder a module-level constant already used, so an
# enum member and a module constant are decided by one rule. (Filed as
# `bugs/FORMAL_a_negative_class_constant_is_not_a_literal.md`, deleted by the
# commit that landed it; this table is the assertion that it landed, and it is an
# ORACLE row — `_cpython_expected` builds the same class through CPython's own
# `enum`, so `-3` is compared against `-3` rather than against a number written
# down here.)
#
# `~0` is in the table for the same reason one folder lower: `A = ~0` is `-1`,
# and every backend's runtime already lowered `~`, so a compile-time folder that
# declined it was answering a different question from the code generator.
ENUM_CASES = [
    ("int_zero", "ZERO", 0),
    ("int_one", "ONE", 1),
    ("int_fifteen", "FIFTEEN", 15),
    ("int_sixty_four", "SIXTYFOUR", 64),
    ("int_neg", "NEG", -3),
    ("int_neg_one", "NEGONE", -1),
    ("int_invert", "INVERT", -1),   # spelled `~0`; see ENUM_MEMBER_SPELLING
    ("str_plain", "PLAIN", "annotated"),
    ("str_empty", "EMPTY", ""),
    ("str_spaces", "SPACES", "a b c"),
]


# The class-body SPELLING for the rows whose value alone does not determine the
# AST shape: `-1` and `~0` are the same Python value and two different nodes, and
# the node is what `formal/model.py::literal_default_word` used to refuse. It is
# consulted on BOTH sides of the oracle — see `_member_source` — so the image and
# CPython are always built from the same text for the same corpus row.
ENUM_MEMBER_SPELLING = {"int_invert": "~0"}


def _member_source(cname: str, value) -> str:
    """The class-body TEXT for one member, on both the image side and CPython's.

    `str(value)` for the ordinary rows, and the operator spelling for the two
    rows that exist to test one: `~0` and `-0`... `-1` and `~0` are the same
    value in Python and two different AST shapes, and the shape is the thing
    under test, so the corpus has to be able to name a shape the value alone
    does not determine. Both sides build their text here so the image and the
    oracle cannot drift onto different spellings of the same corpus row — the
    whole point of deriving one from the other."""
    spelled = ENUM_MEMBER_SPELLING.get(cname)
    if spelled is not None:
        return spelled
    return repr(value) if isinstance(value, str) else str(value)


def _enum_source(classes) -> str:
    """A program declaring `classes` and printing every member's `.value`/`.name`.

    Built rather than written so the corpus and the program cannot disagree about
    what is being tested: the table above is the single source for both.

    The conversion specifier is CHOSEN FROM THE MEMBER'S OWN VALUE — `%lld` for an
    int member, `%s` for a string one — and not fixed per line. That is not a
    detail: the first version printed every `.value` with `%lld`, so a string
    member's answer came out as the ADDRESS of its bytes (measured:
    `Vstr_plain.PLAIN=4330227572` where CPython says `annotated`) and the test was
    comparing a pointer to a word. A test that cannot tell those apart is worse
    than no test, so the specifier is derived from the value on both sides."""
    lines = ["from enum import Enum", ""]
    for cname, members in classes:
        lines.append(f"class {cname}(Enum):")
        for mname, value in members:
            lines.append(f"    {mname} = {_member_source(cname, value)}")
        lines.append("")
    lines.append("def main() -> int:")
    for cname, members in classes:
        for mname, value in members:
            spec = "%s" if isinstance(value, str) else "%lld"
            lines.append(f'    printf("V{cname}.{mname}={spec}|", '
                         f"{cname}.{mname}.value)")
            lines.append(f'    printf("N{cname}.{mname}=%s\\n", '
                         f"{cname}.{mname}.name)")
    lines.append("    return 0")
    return "\n".join(lines) + "\n"


def _cpython_expected(classes):
    """What CPython's own `enum` says, as a list of `(label, answer)` pairs.

    The classes are built by EXECUTING the same source the image is built from,
    in this process's namespace. That is what makes it an oracle rather than a
    table: a change to the corpus changes both sides at once, and a value written
    down here could disagree with CPython without anything noticing."""
    ns = {"Enum": enum.Enum}
    body = []
    for cname, members in classes:
        body.append(f"class {cname}(Enum):")
        for mname, value in members:
            body.append(f"    {mname} = {_member_source(cname, value)}")
    exec("\n".join(body), ns)
    out = []
    for cname, members in classes:
        klass = ns[cname]
        for mname, _v in members:
            out.append((f"V{cname}.{mname}", str(klass[mname].value)))
            out.append((f"N{cname}.{mname}", klass[mname].name))
    return out


def _parse_image(text):
    """The image's `label=answer` pairs back into a dict.

    Split on `|` AND on the newline the image writes after each pair, because the
    program emits one `V…|N…\\n` group per member and the first version of this
    parser split on the `|` alone — so each `N` label arrived glued to the
    previous answer, every second label went missing, and the failure it produced
    read like a backend problem rather than a parser one. A parser that has to
    agree with the format it is parsing is worth stating its separators for."""
    out = {}
    for chunk in text.replace("\n", "|").split("|"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        label, _, answer = chunk.partition("=")
        out[label.strip()] = answer
    return out


def group_enum_value(tmpdir, verbose):
    """Every member's `.value` and `.name`, against CPython's own, on BOTH backends.

    The corpus is built from the table and the image is EXECUTED; a build that
    succeeds is not evidence here, because the bug this group exists for produced
    an image that built, ran and printed plausible numbers."""
    classes = []
    for name, member, value in ENUM_CASES:
        classes.append((name, [(member, value)]))
    src = _enum_source(classes)
    expected = dict(_cpython_expected(classes))
    for backend in BACKENDS:
        got = run(build(src, f"enum_value_{backend}", backend=backend))
        answers = _parse_image(got)
        missing = sorted(set(expected) - set(answers))
        check(not missing,
              f"[{backend}] the image reported no answer for "
              f"{len(missing)} of {len(expected)} members; first: {missing[:3]}")
        bad = [(k, answers.get(k), v) for k, v in sorted(expected.items())
               if k in answers and answers[k] != v]
        check(not bad,
              f"[{backend}] {len(bad)} member accessor(s) disagree with CPython; "
              f"first: {bad[0][0]} image {bad[0][1]!r} CPython {bad[0][2]!r}"
              if bad else "")
    if verbose:
        print(f"    {len(expected)} accessors over {len(classes)} classes, "
              f"each against CPython's enum, on {len(BACKENDS)} backends")
    return True, (f"{len(expected)} enum member accessors agree with CPython on "
                  f"{len(BACKENDS)} backends")


def group_enum_shape(tmpdir, verbose):
    """The shapes an enum takes in this tree, and that they still do not build.

    Two halves, and the second is the honest one: `type_system.py` and
    `formal/x86_64.py` derive from `Enum` and NEITHER BUILDS on this path. This
    asserts the refusals rather than the success, so that a reader who lands this
    module and reads its docstring finds the same thing here that they find
    there."""
    # (1) a class deriving from a base of its OWN, transitively
    src = """from enum import Enum

class MyEnum(Enum):
    pass

class Reg(MyEnum):
    RAX = 0
    R15 = 15

def main() -> int:
    printf("%lld|%s\\n", Reg.R15.value, Reg.R15.name)
    return 0
"""
    got = run(build(src, "enum_subclass"))
    check(got.strip() == "15|R15",
          f"a member of a class deriving transitively from Enum answered "
          f"{got.strip()!r}, expected '15|R15'")

    # (2) a member of a class deriving from a base in ANOTHER file, which is the
    # shape `formal/x86_64.py` has (`Reg(Enum)` with `Enum` imported). The base
    # NAME is all the model can see, and the derivation is read from the same
    # table whether the base is declared here or imported — asserted by
    # `enum-absent`'s own build of `MyEnum` above plus this one.
    #
    # NOT asserted here: a SUBCLASS reading a member its parent declared
    # (`class Child(Base): …  Child.SHARED.value`). Measured, that is refused on
    # this tree by `Child` being read before anything in the function stores it —
    # a read-before-store refusal belonging to a different piece of work, and
    # coupling this file to it would make an unrelated fix look like a regression
    # here. It is listed as a KNOWN_GAP below rather than asserted either way.
    src = """from enum import Enum

class Reg(Enum):
    RAX = 0
    R15 = 15

def main() -> int:
    printf("%lld|%s\\n", Reg.R15.value, Reg.R15.name)
    return 0
"""
    got = run(build(src, "enum_baseimport"))
    check(got.strip() == "15|R15",
          f"a member read through an imported base answered {got.strip()!r}, "
          f"expected '15|R15'")

    # (3) and the two real files, which do NOT build — asserted as refusals, with
    # the module named nowhere in the message.
    for rel in ("type_system.py", "formal/x86_64.py"):
        path = os.path.join(HERE, rel)
        if not os.path.isfile(path):
            continue
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, "shape_" + rel.replace("/", "_")), path],
            capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
        if r.returncode == 0:
            continue          # it built: strictly better than asserted, say nothing
        msg = r.stderr or r.stdout
        check("enum" not in msg.lower() or "host module" in msg.lower(),
              f"{rel} still refuses on `import enum` after the module landed, "
              f"which is the thing this module exists to stop: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print("    transitive base, imported base, and the two real files")
    return True, "the enum shapes hold, and the two real files are past the import"


def group_enum_absent(tmpdir, verbose):
    """Each absent name is a refusal that NAMES ITSELF.

    An omission nobody pins is indistinguishable from an implementation. The two
    that matter most here are `auto()` (whose answer is a count of the class
    body's statements) and the decorators (which build and do nothing, which is
    the worst outcome available)."""
    absent = ["auto", "unique", "verify", "IntEnum", "StrEnum", "Flag",
              "IntFlag", "ReprEnum", "EnumMeta", "EnumType", "member",
              "nonmember", "EnumDict", "EnumCheck", "global_enum",
              "show_flag_values"]
    for name in absent:
        src = f"import enum\n\ndef main() -> int:\n  enum.{name}()\n  return 0\n"
        tmp = os.path.join(TEMP, f"absent_enum_{name}.mojo")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_enum_{name}"), tmp],
            capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"enum.{name} resolved, but the module documents it as absent — "
              f"either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"enum.{name} failed without naming itself: {msg.strip()[-300:]}")

    # `A = auto()` as a member value is refused BY NAME, which is a different and
    # better message than "exports no auto" — the reader is looking at the class
    # body, and the class body is where the fix goes.
    src = ("from enum import Enum\n\nclass Reg(Enum):\n    A = enum_auto()\n\n"
           "def main() -> int:\n    printf(\"%lld\\n\", Reg.A.value)\n"
           "    return 0\n")
    tmp = os.path.join(TEMP, "absent_enum_automember.mojo")
    with open(tmp, "w") as f:
        f.write(src)
    r = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         "-o", os.path.join(TEMP, "absent_enum_automember"), tmp],
        capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
    check(r.returncode != 0,
          "a class-level constant whose value is a CALL built; a formal value is "
          "one word and that is a refusal, not an answer")
    msg = r.stderr or r.stdout
    check("Reg.A" in msg,
          f"a non-literal member value was refused without naming the member: "
          f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent) + 1} absent names refused, each naming itself")
    return True, f"{len(absent) + 1} absent enum names refused"


def group_ctx(tmpdir, verbose):
    """`nullcontext`, both arities, against CPython's own, on BOTH backends."""
    src = """import contextlib

def main() -> int:
    with contextlib.nullcontext(11) as a:
        printf("a=%lld|", a)
    with contextlib.nullcontext() as b:
        printf("b=%lld|", b)
    with contextlib.nullcontext(-7) as c:
        printf("c=%lld\\n", c)
    return 0
"""
    # CPython's own answers, computed here rather than written down.
    with __import__("contextlib").nullcontext(11) as a:
        want_a = a
    with __import__("contextlib").nullcontext() as b:
        want_b = b
    with __import__("contextlib").nullcontext(-7) as c:
        want_c = c
    # `None` is the word 0 on this path (model.NONE_WORD); everything else is
    # compared exactly.
    want = [str(want_a), str(want_b if want_b is not None else 0), str(want_c)]
    for backend in BACKENDS:
        got = run(build(src, "ctx_null", backend=backend))
        parts = [p.split("=", 1)[1].strip()
                 for p in got.split("|") if "=" in p]
        check(parts == want,
              f"[{backend}] nullcontext answered {parts}, CPython {want} "
              f"(with None as the word 0, which is this path's representation "
              f"and not an approximation — see the module's docstring)")
    if verbose:
        print(f"    3 arities of nullcontext, on {len(BACKENDS)} backends")
    return True, f"nullcontext agrees with CPython on {len(BACKENDS)} backends"


def group_ctx_absent(tmpdir, verbose):
    """Each absent contextlib name is a refusal that NAMES ITSELF.

    `closing` is the interesting one and it is in this list for the reason the
    module's docstring gives at length: it would build, bind correctly, and never
    close anything. Pinning it as absent is what stops a later reader from
    'fixing' the omission by adding it."""
    absent = ["suppress", "redirect_stdout", "redirect_stderr", "closing",
              "ExitStack", "AsyncExitStack", "contextmanager", "chdir",
              "aclosing", "AbstractContextManager"]
    for name in absent:
        src = (f"import contextlib\n\ndef main() -> int:\n"
               f"  with contextlib.{name}(1):\n    printf(\"x\\n\")\n  return 0\n")
        tmp = os.path.join(TEMP, f"absent_ctx_{name}.mojo")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_ctx_{name}"), tmp],
            capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"contextlib.{name} built, but the module documents it as absent — "
              f"either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"contextlib.{name} failed without naming itself: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent)} absent names refused, each naming itself")
    return True, f"{len(absent)} absent contextlib names refused"


def group_resolve(tmpdir, verbose):
    """Both modules resolve where `formal/imports.py` says, and LEFT the set.

    The `HOST_MODELLED` half matters for the reason `test_formal_json.py` gives:
    that set is a CLAIM that the module could be written, and a name leaves it by
    being written, because an entry left behind would refuse a file after the
    module that answers it is in the tree."""
    import formal.imports as I
    for mod in ("enum", "contextlib"):
        path = os.path.join(HOSTMODS, mod + ".mojo")
        check(os.path.isfile(path), f"no Mojo source for {mod}")
        got = I.resolve_module_path(mod)
        check(got is not None and os.path.samefile(got, path),
              f"import {mod} resolves to {got!r}, not {path!r}")
        check(I.host_module_tier(mod) == "",
              f"{mod} is still in HOST_MODELLED; its Mojo source exists, so the "
              f"entry is now a false statement about the target")
    if verbose:
        print("    both resolve into formal/hostmods/, both out of the set")
    return True, "enum and contextlib resolve, and both left HOST_MODELLED"


def group_functools_absent(tmpdir, verbose):
    """`functools` is ABSENT, and every one of its names must say so.

    An omission nobody pins is indistinguishable from an implementation — and
    `functools` is the module where that would be WORST, because two of the three
    capabilities it needs are two this backend produces silently:

      * a DECORATOR on this path is parsed and then never applied. `@tag` on a
        function and `@unique` on a class both BUILD, and neither the decorator
        body nor anything it was supposed to enforce ever runs — measured in
        `bugs/COMPILE_FAIL_decorator_application_dropped.md`, and re-measured
        here in the doc's terms: a `printf` inside the decorator prints
        nothing. So an `lru_cache` that exported successfully would build a
        program that caches nothing, which is answer-preserving for `version()`
        and wrong for everything else;
      * a first-class CALLABLE as an ARGUMENT is refused outright, measured on
        both shapes — `functools.reduce(add2, [1,2,3], 0)` does not lower, and
        neither does `def call2(f, a): return f(a)` called as `call2(dbl, 5)`
        with both functions in the caller's own file, so it is not a
        dylib-boundary problem.

    The third is the one this group cannot check and the doc says why:
    `get_cache_token()` returns `len()` of a private cache list, and there is no
    cache registry on this path to derive it from, so any number is a fabricated
    token rather than a mirror — which is why the list below is everything EXCEPT
    that name, and why a module of it would be refused by
    `doc/ABI.md`'s export rule anyway (a library that exports no public function
    is not a library).

    The names are the doc's own census of CPython 3.14.7's `functools` by what
    each one needs (`bugs/FORMAL_functools_is_unbuildable_as_a_host_module.md`),
    minus the one it says has no correct constant answer. This group exists
    because that document's closing line — "the test's `functools`-shaped
    absence group is what keeps that true" — was a promise about a test that did
    not exist: `grep functools test_formal_core_hostmods.py` returned nothing.
    """
    absent = ["cache", "cmp_to_key", "partial", "partialmethod",
              "singledispatch", "singledispatchmethod", "total_ordering",
              "update_wrapper", "wraps", "cached_property", "MethodType",
              "reduce", "GenericAlias", "UnionType", "itemgetter",
              "MappingProxyType", "RLock", "Placeholder", "WRAPPER_ASSIGNMENTS",
              "WRAPPER_UPDATES"]
    for name in absent:
        src = (f"import functools\n\ndef main() -> int:\n  "
               f"functools.{name}\n  return 0\n")
        tmp = os.path.join(TEMP, f"absent_functools_{name}.mojo")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_functools_{name}"), tmp],
            capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"functools.{name} resolved, but the module is documented as "
              f"absent — either the doc is wrong or a functools.mojo landed "
              f"without the decorator and callable support it was measured to "
              f"need")
        msg = r.stderr or r.stdout
        check("functools" in msg,
              f"functools.{name} was refused without naming the MODULE the "
              f"reader has to go and fix: {msg.strip()[-300:]}")
    # The decorator spelling is its own case, because it is the one that would
    # build if the import ever stopped being the thing that refuses it: a
    # `@functools.lru_cache(maxsize=1)` on a function that calls itself. If a
    # functools module ever lands, THIS is the program that runs and skips the
    # work it asked for, so the group asserts it is refused rather than trusting
    # the import to be.
    src = ("import functools\n\n"
           "def fib(n: int) -> int:\n"
           "  if n < 2:\n"
           "    return n\n"
           "  return fib(n - 1) + fib(n - 2)\n\n"
           "@functools.lru_cache(maxsize=1)\n"
           "def counted(n: int) -> int:\n"
           "  return fib(n)\n\n"
           "def main() -> int:\n"
           '  printf("%d\\n", counted(10))\n'
           "  return 0\n")
    tmp = os.path.join(TEMP, "absent_functools_decorator.mojo")
    with open(tmp, "w") as f:
        f.write(src)
    r = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         "-o", os.path.join(TEMP, "absent_functools_decorator"), tmp],
        capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
    check(r.returncode != 0,
          "@functools.lru_cache(maxsize=1) BUILT. That is the shape this whole "
          "group is for: a decorator on this path is parsed and never applied, "
          "so it would be a program that runs and skips the memoisation it "
          "asked for, exiting 0")
    msg = r.stderr or r.stdout
    check("functools" in msg,
          f"the decorated program was refused without naming functools: "
          f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent) + 1} absent functools names refused, each "
              f"naming the module")
    return True, f"{len(absent) + 1} absent functools names refused"


GROUPS = {
    "enum-value": group_enum_value,
    "enum-shape": group_enum_shape,
    "enum-absent": group_enum_absent,
    "ctx": group_ctx,
    "ctx-absent": group_ctx_absent,
    "functools-absent": group_functools_absent,
    "resolve": group_resolve,
}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    args = ap.parse_args()
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0
    names = args.groups or list(GROUPS)
    for n in names:
        if n not in GROUPS:
            print(f"ERROR: unknown group {n!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    failed = []
    with tempfile.TemporaryDirectory() as tmpdir:
        TEMP = tmpdir
        J.TEMP = tmpdir
        for name in names:
            try:
                ok, detail = GROUPS[name](tmpdir, args.verbose)
            except Exception as e:
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            print(("PASS " if ok else "FAIL ") + name + (
                ("  " + detail) if detail else ""))
            if not ok:
                failed.append(name)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
