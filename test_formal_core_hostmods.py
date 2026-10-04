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
import builtins
import enum
import operator
import os
import platform
import signal
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


def run_streams(out):
    """Execute the image and return `(stdout, stderr)`, both as latin-1 text.

    Needed by the `tb` group and by nothing else here: `traceback.print_exc`
    writes to descriptor 2 by definition, so a driver that kept only stdout
    would report the module's one effect as silence and the group would pass on
    a `print_exc` that wrote nothing at all — which is the specific wrong
    answer the module's docstring says CPython does NOT give.

    latin-1 for both, for the reason `run` gives: it round-trips every byte, so
    a body that contains one is not silently mangled into the separator.
    """
    r = subprocess.run([out], capture_output=True, timeout=J.RUN_TIMEOUT,
                       cwd=HERE)
    check(r.returncode == 0,
          f"image exited {r.returncode}: "
          f"{(r.stderr or b'').decode('utf-8', 'replace').strip()[-300:]}")
    return (r.stdout.decode("latin-1"), r.stderr.decode("latin-1"))

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
# `“FORMAL_a_negative_class_constant_is_not_a_literal: `-3` is an `UnaryOp`”`, deleted by the
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
    for mod in ("enum", "contextlib", "traceback", "signal", "operator"):
        path = os.path.join(HOSTMODS, mod + ".mojo")
        check(os.path.isfile(path), f"no Mojo source for {mod}")
        got = I.resolve_module_path(mod)
        check(got is not None and os.path.samefile(got, path),
              f"import {mod} resolves to {got!r}, not {path!r}")
        check(I.host_module_tier(mod) == "",
              f"{mod} is still in HOST_MODELLED; its Mojo source exists, so the "
              f"entry is now a false statement about the target")
    if verbose:
        print("    all five resolve into formal/hostmods/, all five out of "
              "the set")
    return True, ("enum, contextlib, traceback, signal and operator resolve, "
                  "and all five left HOST_MODELLED")


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


# ── `traceback` and `signal` ───────────────────────────────────────────────────
#
# BOTH IN THIS FILE for the reason the docstring's second section gives: a
# handful of names whose answers are CPython's (or the C library's) to give, and
# a file each that wanted one of them. Neither module is large enough to be worth
# a suite of its own and both are in the same shape — a vocabulary plus a
# function or two, with the absences carrying the argument.
#
# `SIGNAL_NAMES` is a list of NAMES and not of numbers, read off this process's
# live `signal`, for the reason `IO_ANSWERS` in `test_formal_small_hosts.py` is:
# the oracle is the interpreter's own module, so a number typed here could be
# wrong without anything noticing, and a name CPython stopped exporting would be
# a corpus row testing a name that does not exist. The image and CPython are
# therefore always asked about the SAME set of names, computed once.
SIGNAL_NAMES = [n for n in dir(signal) if n.startswith("SIG")] + \
               [n for n in dir(signal) if n.startswith("ITIMER_")]
# Sorted so the generated program's order does not depend on `dir()`'s, which is
# a set order and would otherwise make a diff of the two sides unreadable.
SIGNAL_NAMES.sort()


def group_tb(tmpdir, verbose):
    """`traceback.format_exc()` and `print_exc()`, against CPython's, on BOTH backends.

    The whole module, so this group is the module's argument. **Both streams are
    compared**, and the stderr half is the one that matters: `print_exc` writing
    NOTHING is the plausible wrong answer — it is what a reader would expect of a
    module with no exceptions — and it is wrong about this host, which prints
    `NoneType: None` for every call that finds no exception in flight. CPython's
    answer is computed here, in this process, rather than written down.

    The `format_exc` case is asked FIRST and printed to stdout, so a group that
    only ever compared stdout would see a difference even if `print_exc` were
    deleted — the two halves are independent reads of the same string.
    """
    want_fmt = __import__("traceback").format_exc()
    want_print = __import__("traceback").format_exc()
    src = ("import traceback\n\ndef main() -> int:\n"
           '    printf("F=[%s]\\n", traceback.format_exc())\n'
           "    traceback.print_exc()\n"
           "    return 0\n")
    for backend in BACKENDS:
        out = build(src, f"tb_{backend}", backend=backend)
        got_out, got_err = run_streams(out)
        check(got_out == f"F=[{want_fmt}]\n",
              f"[{backend}] traceback.format_exc() answered {got_out!r}, CPython "
              f"{want_fmt!r} — this target has no exception in flight and "
              f"CPython prints this exact text in that state, so a difference "
              f"here is a difference about the text and not about the state")
        check(got_err == want_print,
              f"[{backend}] traceback.print_exc() wrote {got_err!r} to "
              f"descriptor 2, CPython writes {want_print!r}. Writing NOTHING "
              f"is the wrong answer here and this group is what says so")
    if verbose:
        print(f"    format_exc and print_exc, on {len(BACKENDS)} backends, "
              f"stdout AND stderr")
    return True, f"traceback agrees with CPython on {len(BACKENDS)} backends"


def group_tb_absent(tmpdir, verbose):
    """Each absent `traceback` name is a refusal that NAMES ITSELF.

    The list is the module's "WHAT IS NOT HERE, AND WHY" verbatim, and the two
    entries that could have gone the other way are in it for the reason that
    section gives: `print_stack`/`format_stack` are about the CURRENT stack,
    which this target HAS, so a fixed string there would be a plausible wrong
    answer about the program it claimed to describe; and `clear_frames` is about
    MUTATING a traceback the caller holds, which a one-word value has nowhere to
    put.
    """
    absent = ["format_exception", "print_exception", "format_exception_only",
              "format_stack", "print_stack", "print_tb", "format_tb",
              "extract_tb", "walk_tb", "clear_frames", "TracebackException",
              "FrameSummary", "StackSummary", "print_exception_only"]
    for name in absent:
        # A CALL, not a bare name: a bare `traceback.format_stack` is a read of a
        # module-level name, refused for a different and vaguer reason that does
        # not name the name being asked for. Same reason `group_ctx_absent` and
        # `test_formal_small_hosts.py`'s `absent` group give.
        src = (f"import traceback\n\ndef main() -> int:\n"
               f"  printf(\"%s\", traceback.{name}(0))\n  return 0\n")
        tmp = os.path.join(TEMP, f"absent_tb_{name}.mojo")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_tb_{name}"), tmp],
            capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"traceback.{name} resolved, but the module documents it as absent "
              f"— either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"traceback.{name} failed without naming itself: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent)} absent names refused, each naming itself")
    return True, f"{len(absent)} absent traceback names refused"


def group_sig(tmpdir, verbose):
    """Every `signal` NAME against CPython's live `signal`, plus two libc calls.

    Three things, and each is a different kind of claim:

      * **the vocabulary** — every name CPython's `signal` exports, compared one
        by one. It is a list of NAMES read off this process's module, so the two
        sides are always asked about the same set, and a constant that were wrong
        on one platform only (`SIGSTKFLT` is 16 on Linux and absent here;
        `SIGCHLD` is 17 on Linux and 20 here) cannot pass unnoticed. NO SKIP on a
        non-Darwin host: a disagreement there is a true statement about this file,
        and a skip would be how a platform-specific model becomes a
        platform-independent one by accident;
      * **`strsignal`** over every signal number the platform has, byte for byte.
        Not a table: the C library's own text is what has to match, and on this
        platform it carries the number (`"Terminated: 15"`), which is why a
        hand-written table would have been right on Linux and wrong here;
      * **`raise_signal`**, with `SIGCONT` and nothing else — it is the only
        signal whose default disposition continues a running process, so it is
        the only one a test may send to itself.
    """
    src = ["import signal", "", "def main() -> int:"]
    for n in SIGNAL_NAMES:
        src.append(f'    printf("{n}=%d\\n", signal.{n})')
    src.append("    return 0")
    src = "\n".join(src) + "\n"
    want = {}
    for n in SIGNAL_NAMES:
        want[n] = str(getattr(signal, n))
    for backend in BACKENDS:
        got = _parse_image(run(build(src, f"sig_{backend}", backend=backend)))
        bad = {n: (got.get(n), want[n]) for n in SIGNAL_NAMES
               if got.get(n) != want[n]}
        check(not bad,
              f"[{backend}] signal vocabulary disagrees with CPython on "
              f"{len(bad)} name(s): "
              + ", ".join(f"{n}: image {a!r} CPython {b!r}"
                          for n, (a, b) in sorted(bad.items()))
              + " — these are this platform's <signal.h> numbers and they are "
                "the ones CPython's own module reports on this host")

    # `strsignal`, one build per backend, every number the platform has.
    sig_src = ["import signal", "", "def main() -> int:"]
    for n in range(1, int(signal.NSIG)):
        sig_src.append(f'    printf("{n}=%s|", signal.strsignal({n}))')
    sig_src.append("    return 0")
    sig_src = "\n".join(sig_src) + "\n"
    for backend in BACKENDS:
        got = _parse_image(run(build(sig_src, f"sig_str_{backend}",
                                     backend=backend)))
        bad = {}
        for n in range(1, int(signal.NSIG)):
            answer = signal.strsignal(n)
            if got.get(str(n)) != answer:
                bad[n] = (got.get(str(n)), answer)
        check(not bad,
              f"[{backend}] signal.strsignal disagrees with CPython on "
              f"{len(bad)} of {int(signal.NSIG) - 1} signal number(s): "
              + ", ".join(f"{n}: image {a!r} CPython {b!r}"
                          for n, (a, b) in sorted(bad.items()))
              + " — the answer is the C library's own text, so any difference "
                "here is a difference about which strsignal(3) ran")

    # `raise_signal(SIGCONT)`: CPython answers None, which is the word 0 here.
    raise_src = ("import signal\n\ndef main() -> int:\n"
                 '    printf("r=%d\\n", signal.raise_signal(signal.SIGCONT))\n'
                 "    return 0\n")
    want_raise = 0 if signal.raise_signal(signal.SIGCONT) is None else \
        signal.raise_signal(signal.SIGCONT)
    for backend in BACKENDS:
        got = run(build(raise_src, f"sig_raise_{backend}", backend=backend))
        check(got == f"r={want_raise}\n",
              f"[{backend}] signal.raise_signal(SIGCONT) answered {got!r}, "
              f"CPython answers None and None is the word 0 on this path "
              f"(model.NONE_WORD) — see the module's docstring")
    if verbose:
        print(f"    {len(SIGNAL_NAMES)} signal names, "
              f"{int(signal.NSIG) - 1} strsignal answers and raise_signal, on "
              f"{len(BACKENDS)} backends")
    return True, (f"{len(SIGNAL_NAMES)} signal names and "
                  f"{int(signal.NSIG) - 1} strsignal answers agree with CPython "
                  f"on {len(BACKENDS)} backends")


def group_sig_absent(tmpdir, verbose):
    """Each absent `signal` name is a refusal that NAMES ITSELF.

    `signal` is the module where an omission is most dangerous, and that is why
    the list is the module's own "WHAT IS NOT HERE" verbatim rather than a
    sample: `signal(signum, handler)` would build, record nothing and let the
    program believe it had installed a handler, which is the silent-wrong-answer
    shape `functools-absent` above is entirely about. `Signals` is the other one
    worth naming — `signal.Signals(15).name` is real, useful CPython and needs
    the number and the name to be one value with two readings.
    """
    absent = ["signal", "getsignal", "sigpending", "sigwait",
              "pthread_sigmask", "pthread_kill", "siginterrupt",
              "set_wakeup_fd", "pause", "alarm", "setitimer", "getitimer",
              "valid_signals", "Signals", "Sigmasks", "Handlers",
              "ItimerError", "default_int_handler"]
    for name in absent:
        src = (f"import signal\n\ndef main() -> int:\n"
               f"  printf(\"%s\", signal.{name}(0))\n  return 0\n")
        tmp = os.path.join(TEMP, f"absent_sig_{name}.mojo")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_sig_{name}"), tmp],
            capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"signal.{name} resolved, but the module documents it as absent — "
              f"either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"signal.{name} failed without naming itself: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent)} absent names refused, each naming itself")
    return True, f"{len(absent)} absent signal names refused"


# ── `operator` ─────────────────────────────────────────────────────────────────
#
# A CORPUS OF OPERANDS, and it is a table because a table is the thing that makes
# a corpus a corpus: the point is not that `operator.add(3, 4)` is 7, it is that
# every answer agrees with CPython's over operands chosen to separate one rule
# from another.
#
# The four rows that exist to catch a specific wrong answer:
#
#   (0, 0)             — every name must answer 0 or 1 here, and `floordiv`/`mod`
#                        must be the -1 status rather than a crash;
#   a NEGATIVE operand  — `mod` FLOORS in CPython (`(0-7) % 2` is 1), which is the
#                        one arithmetic rule a truncating implementation gets
#                        wrong and it is in the table for that;
#   an operand PAST 32 BITS — `%lld` and not `%d`, for the reason every other
#                        test in this tree gives (`bugs/FORMAL_string_value_model.md`
#                        §2): `%d` is 32 bits on this path, so the first version of
#                        this corpus printed `operator.lshift(1, 40)` as 0 where
#                        CPython says 1099511627776, and the test was comparing a
#                        truncation against a power of two;
#   the overflow word   — `(1 << 62) * 4` is 0 HERE and 2**64 in CPython, which is
#                        the value model rather than a defect, so the expected
#                        side of that row is computed by asking the C library what
#                        a 64-bit word does rather than by asking CPython.
OP_CASES = [
    # (name, a, b)
    ("add", 3, 4), ("add", 0 - 3, 4), ("add", 0, 0),
    ("sub", 3, 4), ("sub", 4, 3), ("mul", 6, 7), ("mul", 0 - 1, 0 - 1),
    ("floordiv", 7, 2), ("floordiv", 0 - 7, 2), ("floordiv", 8, 2),
    ("mod", 7, 3), ("mod", 0 - 7, 2), ("mod", 8, 2),
    ("and_", 12, 10), ("or_", 12, 10), ("xor", 12, 10),
    ("and_", 0, 0 - 1), ("or_", 0, 0 - 1), ("xor", 0 - 1, 0 - 1),
    ("lt", 3, 4), ("lt", 4, 3), ("lt", 3, 3),
    ("le", 3, 4), ("le", 4, 3), ("le", 3, 3),
    ("eq", 3, 4), ("eq", 4, 3), ("eq", 3, 3),
    ("ne", 3, 4), ("ne", 4, 3), ("ne", 3, 3),
    ("gt", 3, 4), ("gt", 4, 3), ("gt", 3, 3),
    ("ge", 3, 4), ("ge", 4, 3), ("ge", 3, 3),
    ("lshift", 1, 40), ("lshift", 1, 0), ("lshift", 1, 1),
    ("lshift", 255, 8), ("rshift", 256, 4), ("rshift", 0 - 1, 1),
    ("rshift", 1099511627776, 40),
    # Past the word's width a right shift is a DEFINED answer on both sides
    # (0 for a non-negative word, -1 for a negative one), so these two rows are
    # ordinary comparisons against CPython rather than a status. They are in the
    # corpus because the machine's own `>>` MASKS the distance to six bits and
    # answers 0 for both (measured), which is a silent wrong answer the module's
    # `rshift` exists to avoid.
    ("rshift", 0 - 1, 64), ("rshift", 0 - 3, 100), ("rshift", 1, 100),
    ("lshift", 0, 64), ("lshift", 0, 200),
]

# The UNARY names, as (name, operand), and the two-argument `pow`/`pow_mod` rows
# kept apart because their expected side is computed differently.
OP_UNARY = [
    ("neg", 5), ("neg", 0 - 5), ("neg", 0),
    ("pos", 5), ("pos", 0 - 5),
    ("abs", 5), ("abs", 0 - 5), ("abs", 0),
    ("invert", 0), ("invert", 5),
    ("index", 42), ("index", 0 - 42), ("index", 0),
    ("truth", 0), ("truth", 1), ("truth", 0 - 1),
    ("not_", 0), ("not_", 1), ("not_", 0 - 1),
]

OP_POW = [
    (2, 10), (3, 39), (2, 0), (0, 0), (5, 1), (0 - 2, 3), (2, 62),
]
OP_POW_MOD = [
    (2, 10, 1000), (3, 39, 1000000007), (2, 0, 7), (0, 0, 7),
    (0 - 2, 3, 7), (5, 13, 1),
]

# Where CPython RAISES and this path answers -1. Each row is
# `(the call as this module spells it, WHERE CPython SPELLS IT, its arguments,
# the exception CPython raises)` — four fields because the two `pow` rows resolve
# to different places. CPython's `operator.pow_mod` does not exist: the
# three-argument power is the BUILTIN `pow` and `operator.pow` is two-argument
# only, so a group that asked `operator.pow_mod` got `AttributeError` and one
# that asked `operator.pow` for three arguments got `TypeError` — both of which
# are a test that measured nothing. The module is named WITH its module, so one
# table holds both.
#
# The group asserts the image answers -1 AND that CPython raises the named
# exception, so a status that stopped standing in for the thing it names fails
# rather than passing a comparison against a constant.
OP_STATUSES = [
    ("floordiv(5, 0)", "operator.floordiv", (5, 0), "ZeroDivisionError"),
    ("mod(5, 0)", "operator.mod", (5, 0), "ZeroDivisionError"),
    ("pow_mod(2, 3, 0)", "builtins.pow", (2, 3, 0), "ValueError"),
    ("lshift(1, -1)", "operator.lshift", (1, -1), "ValueError"),
    ("rshift(1, -1)", "operator.rshift", (1, -1), "ValueError"),
]

# THE OTHER TWO WAYS CPython'S ANSWER IS NOT A WORD, as two tables because the
# first version of this group had ONE table for all three and every one of its
# rows was checked, which is how it was found to be two thirds wrong.
#
# `operator.pow(2, -1)` was listed as a `ValueError` and CPython answers `0.5`;
# `operator.lshift(1, 64)` was listed as an `OverflowError` and CPython answers
# `2**64`. Neither is a refusal — CPython answers something — so they do not
# belong beside a `ZeroDivisionError`, and a single table over all three asserts
# a claim about CPython that two of its rows do not make.
#
# A FLOAT answer: this path has no float arithmetic at all (a `double` does not
# travel in an integer register on either ABI — `formal/hostmods/math.mojo`), so
# the module answers -1. Each row asserts its own claim about CPython, that the
# answer is a `float` and is not integral.
OP_NOT_A_WORD = [("pow(2, -1)", (2, -1)), ("pow(3, -2)", (3, -2))]

# A BIGGER integer than one word holds: CPython's `int` is arbitrary-precision,
# this target's is a signed 64-bit word, and `1 << 63` is the first shift whose
# answer does not fit (it is 2**63, and the word's top bit is the sign). The
# hardware MASKS the distance to its low 6 bits, which is why this is a status
# and not `0`.
OP_TOO_BIG = [("lshift(1, 64)", (1, 64)), ("lshift(1, 200)", (1, 200))]

WORD_LIMIT = 1 << 63

# And the FOURTH shape, which is not a refusal and not a wrong answer: an
# operation whose CPython result needs more than a SIGNED word, and which
# therefore WRAPS here. `1 << 63` is 2**63 — inside the 64 bits and outside the
# signed range, so the machine's answer is its own negative. This is the value
# model (`formal/model.py`, "What a value is") and the module's docstring says
# every answer wraps, so it is pinned here against the WRAP rather than against
# CPython: comparing it with CPython would be comparing a 64-bit word with an
# arbitrary-precision integer, which is the category error the other three tables
# exist to keep separate.
#
# The expected value is computed by masking to 64 bits and reinterpreting as
# signed, which is what the C the image is made of does.
OP_WRAPS = [
    ("lshift(1, 63)", (1, 63)),
    ("mul(4611686018427387904, 4)", (4611686018427387904, 4)),
    ("mul(4000000000, 5000000000)", (4000000000, 5000000000)),
]


def _wrap64(v: int) -> int:
    """`v` as a signed 64-bit word: the two's-complement wrap the machine does."""
    v &= (1 << 64) - 1
    return v - (1 << 64) if v >= (1 << 63) else v



def group_op(tmpdir, verbose):
    """Every `operator` name against CPython's live `operator`, on BOTH backends.

    Three corpora and three kinds of oracle, which is the whole shape of the
    module:

      * `OP_CASES` / `OP_UNARY` / `OP_POW` / `OP_POW_MOD` — compared against
        CPython's own functions applied to the same operands. `operator.pow` is
        CPython's `pow`; `operator.pow_mod` is CPython's three-argument `pow`,
        which is a different SPELLING on this path (the module's docstring says
        why a default cannot express "no modulus") and the same function;
      * the comparisons and `truth`/`not_` answer 1 or 0 where CPython answers a
        `bool`, so the expected side reads CPython's answer through `int()` — the
        oracle is still CPython and the conversion is this path's, and it is
        stated in both places rather than left to be discovered;
      * `OP_STATUSES` — the places CPython raises. There are no exceptions on this
        path, so each answers -1, and the group checks BOTH halves: the image
        answers -1 and CPython raises the exception named beside the row. A
        status that stopped standing in for the thing it names would still pass a
        comparison against a constant.
    """
    src = ["import operator", "", "def main() -> int:"]
    for name, a, b in OP_CASES:
        src.append(f'    printf("{name}({a},{b})=%lld|", operator.{name}({a}, {b}))')
    for name, a in OP_UNARY:
        src.append(f'    printf("{name}({a})=%lld|", operator.{name}({a}))')
    for a, b in OP_POW:
        src.append(f'    printf("pow({a},{b})=%lld|", operator.pow({a}, {b}))')
    for a, b, m in OP_POW_MOD:
        src.append(f'    printf("pow_mod({a},{b},{m})=%lld|", '
                   f'operator.pow_mod({a}, {b}, {m}))')
    src.append("    return 0")
    src = "\n".join(src) + "\n"

    want = {}
    # The six COMPARISONS answer 1 or 0 where CPython answers a `bool`, so their
    # expected side is read through `int()`. That is this path's conversion and
    # not a fudge: the first version of this group compared them directly and 18
    # of 76 cases failed with `image '1' CPython 'True'`, which is the shape of
    # a test that forgot to say which of the two representations it is asserting.
    COMPARISONS = ("lt", "le", "eq", "ne", "gt", "ge")
    for name, a, b in OP_CASES:
        f = getattr(operator, name)
        want[f"{name}({a},{b})"] = str(int(f(a, b)) if name in COMPARISONS
                                       else f(a, b))
    for name, a in OP_UNARY:
        want[f"{name}({a})"] = str(int(getattr(operator, name)(a)))
    for a, b in OP_POW:
        want[f"pow({a},{b})"] = str(operator.pow(a, b))
    for a, b, m in OP_POW_MOD:
        want[f"pow_mod({a},{b},{m})"] = str(pow(a, b, m))

    # And the status rows, in the same program, so one build answers everything.
    status_src = ["import operator", "", "def main() -> int:"]
    for call, _attr, _args, _exc in OP_STATUSES:
        status_src.append(f'    printf("{call}=%lld|", operator.{call})')
    for call, _args in OP_NOT_A_WORD + OP_TOO_BIG + OP_WRAPS:
        status_src.append(f'    printf("{call}=%lld|", operator.{call})')
    status_src.append("    return 0")
    status_src = "\n".join(status_src) + "\n"

    for backend in BACKENDS:
        got = _parse_image(run(build(src, f"op_{backend}", backend=backend)))
        bad = {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}
        check(not bad,
              f"[{backend}] operator disagrees with CPython on {len(bad)} of "
              f"{len(want)} case(s): "
              + ", ".join(f"{k}: image {a!r} CPython {b!r}"
                          for k, (a, b) in sorted(bad.items()))
              + " — every name here is word arithmetic and wraps at 64 bits "
                "like the machine's, which is the value model and not a defect")

        got = _parse_image(run(build(status_src, f"op_status_{backend}",
                                     backend=backend)))
        for call, _attr, _args, exc in OP_STATUSES:
            check(got.get(call) == "-1",
                  f"[{backend}] operator.{call} answered {got.get(call)!r}, not "
                  f"the -1 status — CPython raises {exc} there and this path "
                  f"has no exceptions, so -1 is the answer that is visible "
                  f"rather than plausible (math.mojo's precedent)")

    # The oracle for the statuses is CPython's OWN behaviour, read here, and the
    # exception CLASSES are resolved by name rather than written as objects so
    # the table stays a table of spellings that agree with the module docstring.
    for call, attr, args, exc in OP_STATUSES:
        cls = getattr(builtins, exc, None)
        check(cls is not None and issubclass(cls, BaseException),
              f"OP_STATUSES names {exc!r}, which is not an exception in this "
              f"interpreter, so the status row for {call} has nothing to stand "
              f"in for")
        ns_name, _, bare = attr.partition(".")
        ns = {"operator": operator, "builtins": builtins}.get(ns_name)
        f = getattr(ns, bare, None) if ns is not None else None
        check(f is not None,
              f"OP_STATUSES asks CPython for {attr!r}, which names no module "
              f"this interpreter has, so the status row for {call} has no "
              f"oracle")
        try:
            f(*args)
            check(False,
                  f"CPython's {attr}{args} no longer raises {exc}, so the -1 "
                  f"status this module answers for {call} stands in for "
                  f"nothing and the module's docstring and OP_STATUSES are "
                  f"both stale")
        except cls:
            pass
    # And the two "not a word" tables. Each row asserts its OWN claim about
    # CPython — a float and not integral, or an integer past the word — as well
    # as the image's -1, because a table whose rows are checked on one side only
    # is how `pow(2, -1)` came to be filed as a `ValueError`.
    got = _parse_image(run(build(status_src, "op_noword", backend=BACKENDS[0])))
    for call, args in OP_NOT_A_WORD:
        cpy = operator.pow(*args)
        check(isinstance(cpy, float) and cpy != int(cpy),
              f"CPython's operator.pow{args} answered {cpy!r}, which is an "
              f"integer, so the -1 this module answers for {call} is standing "
              f"in for a different thing than the module's docstring says")
        check(got.get(call) == "-1",
              f"operator.{call} answered {got.get(call)!r}; CPython's answer "
              f"is a float and there is no float here, so the answer is the -1 "
              f"status")
    for call, args in OP_TOO_BIG:
        name, _, rest = call.partition("(")
        cpy = getattr(operator, name)(*args)
        check(abs(cpy) >= WORD_LIMIT,
              f"CPython's operator.{call} answered {cpy!r}, which FITS in a "
              f"signed 64-bit word, so the -1 this module answers for it is "
              f"standing in for nothing and OP_TOO_BIG is stale")
        check(got.get(call) == "-1",
              f"operator.{call} answered {got.get(call)!r}; CPython answers "
              f"{cpy} and this path has 64 bits, so the answer is the -1 "
              f"status")
    for call, args in OP_WRAPS:
        name, _, rest = call.partition("(")
        cpy = getattr(operator, name)(*args)
        check(abs(cpy) >= WORD_LIMIT,
              f"CPython's operator.{call} answered {cpy!r}, which FITS in a "
              f"signed 64-bit word, so the wrap OP_WRAPS pins is not a wrap at "
              f"all and the row is stale")
        check(got.get(call) == str(_wrap64(cpy)),
              f"operator.{call} answered {got.get(call)!r}, and the 64-bit wrap "
              f"of CPython's {cpy} is {_wrap64(cpy)} — a formal value is one "
              f"signed 64-bit word (formal/model.py), so wrapping is the "
              f"value model and not a defect")
    if verbose:
        print(f"    {len(want)} answers, {len(OP_STATUSES)} status rows, "
              f"{len(OP_NOT_A_WORD)} not-a-word rows and {len(OP_WRAPS)} wrap "
              f"rows, on {len(BACKENDS)} backends")
    return True, (f"{len(want)} operator answers agree with CPython on "
                  f"{len(BACKENDS)} backends, and {len(OP_STATUSES)} refusal "
                  f"statuses stand in for the exceptions CPython raises")


def group_op_absent(tmpdir, verbose):
    """Each absent `operator` name is a refusal that NAMES ITSELF.

    Three rows of this list are there because they are the ones a later reader
    would try to add, and the module's docstring gives the reason for each:
    `truediv` (a `float`, and `truediv(4, 2)` would agree while `truediv(7, 2)`
    would not), `iadd` and its eleven siblings (each returns `a + b` AND writes
    it back through a name, so a program that wrote `i = operator.iadd(i, 1)`
    would run and lose the increment), and `itemgetter` (a first-class callable
    as a return value).
    """
    absent = ["truediv", "divmod", "concat", "contains", "countOf", "indexOf",
              "getitem", "setitem", "delitem", "itemgetter", "attrgetter",
              "methodcaller", "call", "length_hint",
              "iadd", "isub", "imul", "itruediv", "ifloordiv", "imod", "ipow",
              "ilshift", "irshift", "iand", "ior", "ixor"]
    for name in absent:
        src = (f"import operator\n\ndef main() -> int:\n"
               f"  printf(\"%lld\", operator.{name}(3, 4))\n  return 0\n")
        tmp = os.path.join(TEMP, f"absent_op_{name}.mojo")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_op_{name}"), tmp],
            capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"operator.{name} resolved, but the module documents it as absent "
              f"— either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"operator.{name} failed without naming itself: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent)} absent names refused, each naming itself")
    return True, f"{len(absent)} absent operator names refused"


GROUPS = {
    "enum-value": group_enum_value,
    "enum-shape": group_enum_shape,
    "enum-absent": group_enum_absent,
    "ctx": group_ctx,
    "ctx-absent": group_ctx_absent,
    "functools-absent": group_functools_absent,
    "tb": group_tb,
    "tb-absent": group_tb_absent,
    "sig": group_sig,
    "sig-absent": group_sig_absent,
    "op": group_op,
    "op-absent": group_op_absent,
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
