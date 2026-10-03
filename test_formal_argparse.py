#!/usr/bin/env python3
"""Tests for the formal backend's `argparse` module.

`formal/hostmods/argparse.mojo` is the Mojo source `formal/imports.py`
resolves `import argparse` to, so `argparse` is no longer in `HOST_MODELLED` and
the eighteen files the sweep listed for it are no longer refused for importing
it. That is worth nothing on its own — a module nothing can call is a rock — so
what is asserted here is:

  1. `import argparse` resolves to the module source, in the resolver's own
     order, and `argparse` is not in `HOST_MODELLED` any more;
  2. every public name in the module reaches a dylib's export table, so a name
     added without checking it cannot produce a module that builds and cannot be
     called;
  3. **THE MODULE BUILDS ON ITS OWN.** `build --formal` of
     `formal/hostmods/argparse.mojo` itself, with nothing importing it. Every
     other assertion here builds a program that IMPORTS the module, which is
     the module's real use — and a refusal raised in the module's own body is
     reachable from those too, so this looks redundant until you count what it
     catches first: it is the only assertion here whose subject is the module
     as a translation unit rather than a program that uses it, which is the
     question "does this file lower?" and the one nobody was asking. Measured:
     `_name_len` and `_fname_len` shipped unannotated, and their results are
     compared against non-literal operands, so the module did not build and
     every program importing it was refused for a diagnostic whose subject is a
     line inside it — `formal/model.py`'s `string_compare_word_refusal`, whose
     own message names the two annotations that clear it;
  4. **THE PARSE IS CPYTHON'S.** One table of parser declarations and command
     lines below drives two generated programs: one that uses CPython's own
     `argparse`, and one that uses this module through `formal/hostmods`. Both
     are built, the second is BUILT AS AN ARM64 IMAGE AND RUN, and their stdout,
     their stderr and their exit status must be identical. Every case in the
     table is either a value, a usage line, an error message or an exit code
     that this module has to reproduce exactly;
  5. the refusals are refusals — `type=float` is declined with a reason rather
     than truncated to an integer, because a value on this path is one 64-bit
     integer word (measured: `2.5` is the integer 2, `atof("3.5")` is 1);
  6. the limits this module is written around are pinned as measurements —
     `int("1_0")` is refused rather than read as 10, and help text is laid out
     but not wrapped — so the next reader finds them in the test rather than
     rediscovering them.

The comparison is against CPython's OWN answers rather than against a table of
expected strings, so a change in either implementation that is wrong in the
same way in both would have to be wrong in CPython to pass.

Invoked directly:
    python3 test_formal_argparse.py [-v]
"""
import argparse
import concurrent.futures
import json
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
ARGPARSE_MODULE = os.path.join(HOSTMODS, "argparse.mojo")

sys.path.insert(0, HERE)

# The independent driver and the assertion helper live in the dylib suite;
# imported rather than copied so a fix to either cannot leave a second, quietly
# different one behind.
from test_formal_dylib import (TestFailure, check, parse_macho,  # noqa: E402
                               run_fire)

# A CAS of this file's own. A module dylib is cached by content, so a stale one
# from an earlier run could mask a regression, and this file must not delete
# libraries out from under a parallel job in a shared bucket.
#
# And ONE PER WORKER, which is not tidiness: the cases below are built
# concurrently, every one of them links the same `argparse` dylib, and two
# builds publishing the same manifest into one CAS race on it — measured, as
# `build failed: fault_decoder.decode(s)` with a JSONDecodeError out of a
# half-written file. A private CAS per worker is content-addressed, so each
# still builds the library once.
_CAS_ROOT = tempfile.mkdtemp(prefix="formal_argparse_cas_")
_CAS_HOME = os.path.join(_CAS_ROOT, "exports")
os.makedirs(_CAS_HOME, exist_ok=True)
os.environ["GMOJO_HOME"] = _CAS_HOME


def _worker_cas(worker):
    """A private CAS for one build worker."""
    home = os.path.join(_CAS_ROOT, "w%d" % worker)
    os.makedirs(home, exist_ok=True)
    return home

BUF_CAP = 8192

# ── The declarations every case is generated from ────────────────────────────
#
# One table, two programs. A case is a parser plus a command line, and each is
# run twice — once through CPython's `argparse` and once through this module's —
# so any difference in the answer is a difference in this module.

PARSERS = [
    dict(
        name="demo",
        prog="demo",
        desc="A demo tool.",
        args=[
            (["-v", "--verbose"], dict(action="store_true")),
            (["-j", "--jobs"], dict(type=int, default=8,
                                    help="worker count")),
            (["--side"], dict(choices=["a", "b"], required=True)),
            (["--extra"], dict(action="append", default=[])),
            (["stems"], dict(nargs="*")),
        ],
        cases=[
            ["--side", "a"],
            ["-v", "--side", "a", "--jobs", "4", "x.py", "y.py"],
            ["--jobs=9", "--side", "b"],
            ["--side", "a", "--extra", "p", "--extra", "q"],
            ["-v"],
            ["--side", "c"],
            ["--side", "a", "--jobs", "zz"],
            ["--side", "a", "-j"],
            ["--side"],
            ["--side", "a", "x", "--no"],
            ["--side", "a", "--jo", "3"],
            ["--side", "a", "-vv"],
            ["--side", "a", "--", "-x"],
            ["--help"],
        ],
    ),
    dict(
        name="flags",
        prog="demo",
        desc="",
        args=[
            (["--no-cache"], dict(action="store_false")),
            (["-q", "--quiet"], dict(action="store_true")),
            (["-v"], dict(action="count", default=0)),
            (["--pass-list"], dict(default=None)),
        ],
        cases=[[], ["--no-cache"], ["-vvv"], ["-q", "--pass-list", "p"]],
    ),
    dict(
        name="pos",
        prog="demo",
        desc="",
        args=[
            (["-v"], dict(action="store_true")),
            (["first"], dict(nargs="*")),
            (["last"], dict()),
        ],
        cases=[["a", "b", "c"], ["a", "b"], ["a", "-v", "b"], ["a", "--", "b"],
               [], ["-v"]],
    ),
    dict(
        name="optargs",
        prog="demo",
        desc="",
        args=[
            (["--opt"], dict(nargs="?", default="D")),
            (["--pass-list"], dict(default=None)),
            (["-j", "--jobs"], dict(type=int, dest="workers", metavar="N")),
        ],
        cases=[[], ["--opt"], ["--opt", "x"], ["-j5"], ["--jobs=7"],
               ["-j", "-3"]],
    ),
    dict(
        name="rem",
        prog="demo",
        desc="",
        args=[
            (["--limit"], dict(type=int, default=55)),
            (["cmd"], dict(nargs=argparse.REMAINDER)),
        ],
        cases=[["--limit", "2", "--", "ls", "-l"], ["x", "y"], []],
    ),
    dict(
        name="intn",
        prog="demo",
        desc="",
        args=[(["--pair"], dict(nargs=2, type=int))],
        cases=[["--pair", "1", "2"], ["--pair", "1"], ["--pair", "1", "2", "3"]],
    ),
    dict(
        name="amb",
        prog="demo",
        desc="",
        args=[(["--jobs"], dict(type=int)), (["--job-count"], dict(type=int))],
        cases=[["--jo", "1"], ["--js", "1"], ["--jobs=2", "--job-count=3"]],
    ),
    dict(
        name="posplus",
        prog="demo",
        desc="",
        args=[(["first"], dict(nargs="+")),
              (["last"], dict(nargs="?"))],
        cases=[["a"], ["a", "b"], []],
    ),
    dict(
        # `nargs="?"` on a POSITIONAL: CPython's `_get_values` answers the
        # action's DEFAULT for it, where an OPTIONAL with `?` answers `const`.
        # Two different answers to "no arguments", and the corpus has one of
        # each shape across its files.
        name="qmark",
        prog="demo",
        desc="",
        args=[(["-v"], dict(action="store_true")),
              (["--opt"], dict(nargs="?", default="D")),
              (["--req"], dict(nargs="?", required=True)),
              (["maybe"], dict(nargs="?", default="M")),
              (["tail"], dict())],
        cases=[["a"], ["--opt", "x", "a"], ["--req", "a"], ["a", "b"],
               ["--opt", "a"], ["--", "-x"]],
    ),
    dict(
        # The shapes a combined short argument can go wrong in: an unknown
        # short flag after a real one, `=` where a flag does not take a value,
        # and an option that looks like a negative number.
        name="shorts",
        prog="demo",
        desc="",
        args=[(["-v"], dict(action="store_true")),
              (["-q"], dict(action="store_true")),
              (["-j"], dict(type=int)),
              (["-n", "--neg"], dict(type=int)),
              (["rest"], dict(nargs="*"))],
        cases=[["-vq"], ["-v=1"], ["-vx"], ["-v", "-j", "4"], ["-j4"],
               ["-n-3"], ["-3"], ["-v", "--", "-q"], ["-jq", "4"]],
    ),
    # ── the three places help text is FOLDED ─────────────────────────────────
    #
    # `bugs/FORMAL_argparse_help_wrapping_not_implemented.md`: the layout was
    # reproduced and nothing was folded, so a help string past the column came
    # out on one line and a usage line past the width came out on one line. These
    # three parsers are the shapes that reach each of the three algorithms, which
    # are three and not one: the help column and the description are
    # `textwrap.wrap` (at `max(width - help_position, 11)` and at the full width),
    # and the usage line is `_format_usage`'s own fold over PARTS, which never
    # splits one and is therefore not `textwrap` at all.
    #
    # Every help string here avoids `;` and `|`, which are this module's spec's
    # record and field separators — a help string containing one is truncated at
    # it, which CPython allows and this representation cannot hold
    # (`bugs/FORMAL_argparse_spec_separators_in_a_help_string.md`) — and every
    # description avoids `"` and `\`, which the generated program embeds
    # verbatim.
    dict(
        name="wrapentry",
        prog="demo",
        desc=("A description long enough that CPython folds it onto a second "
              "line at the 78 columns this target knows, since a terminal "
              "cannot be asked for here and nothing shorter will do."),
        args=[
            # Wrapped at the help column, with the break landing mid-sentence.
            (["-j", "--jobs"], dict(type=int, default=8,
                                    help="the number of workers to run in "
                                         "parallel, and more than the core "
                                         "count is usually slower")),
            # A HYPHENATED word: `textwrap` breaks after the hyphen, which is a
            # different rule from the one that fills a line.
            (["--no-cache"], dict(action="store_false",
                                  help="turn the cache off. --no-cache is "
                                       "hyphenated and this help text is long "
                                       "enough to fold twice")),
            # One word longer than the column, which is broken mid-word.
            (["-x"], dict(action="store_true",
                          help="supercalifragilisticexpialidocious-and-then-"
                               "some is one run of characters")),
            (["--opt"], dict(choices=["alpha", "beta"], default="alpha",
                             help="short")),
        ],
        cases=[["--help"]],
    ),
    dict(
        # A usage line past the width, with a SHORT prog: the prog shares the
        # first line with the optionals and the positionals are folded after
        # them.
        name="usagefold",
        prog="demo",
        desc="",
        args=[
            (["--input-directory"], dict(default="in")),
            (["--output-directory"], dict(default="out")),
            (["--jobs"], dict(type=int, default=1)),
            (["--keep-going"], dict(action="store_true")),
            (["--verbose"], dict(action="count", default=0)),
            (["--dry-run"], dict(action="store_true")),
            (["paths"], dict(nargs="*")),
        ],
        cases=[["--help"]],
    ),
    dict(
        # The same fold with a LONG prog (past `0.75 * width`), which is the
        # other branch: the prog gets a line of its own.
        name="longprog",
        prog="a-program-name-long-enough-to-need-a-usage-line-of-its-own",
        desc="",
        args=[
            (["--input-directory"], dict(default="in")),
            (["--output-directory"], dict(default="out")),
            (["--keep-going"], dict(action="store_true")),
            (["paths"], dict(nargs="*")),
        ],
        cases=[["--help"]],
    ),
    dict(
        # `metavar`, an explicit `dest`, and help text on a positional: the
        # three ways the usage line and the help listing can disagree about
        # what an action is called.
        name="metavar",
        prog="demo",
        desc="A longer description that is still inside the width.",
        args=[(["-j", "--jobs"], dict(type=int, dest="workers", metavar="N",
                                     help="how many")),
              (["--opt"], dict(choices=["alpha", "beta"], default="alpha",
                               help="which one")),
              (["paths"], dict(nargs="*", help="what to do"))],
        cases=[[], ["-j", "2"], ["--opt", "beta"], ["--opt", "gamma"],
               ["--help"], ["a", "b"]],
    ),
]

# ── Generating the two programs from one declaration ──────────────────────────
#
# The spec this module reads is derived from the same `add_argument` call that
# the CPython program makes, so a case cannot be wrong in one program and right
# in the other because the two were written down separately.

def nargs_field(nargs):
    """A CPython `nargs` as this module's one-character spelling."""
    if nargs is None:
        return ""
    if nargs == "*":
        return "*"
    if nargs == "+":
        return "+"
    if nargs == "?":
        return "?"
    if nargs == argparse.REMAINDER:
        return "R"
    return str(nargs)


def default_field(default):
    """A Python default as the text this module stores.

    A bool is stored as `1`/`0` because that is what `store_true` and `count`
    hold on this target, and the canonical form prints both as a number; a list
    as its source spelling, of which only `[]` occurs.
    """
    if default is None:
        return "~"                    # an EXPLICIT None; see the module's
    if isinstance(default, bool):    # NONE_TEXT and the difference from an
        return "1" if default else "0"    # omitted default, which matters for
    return str(default)              # store_true and count


def record_for(names, kw):
    """One `add_argument` call as one record of this module's spec."""
    ty = ""
    if "type" in kw:
        ty = {int: "int", str: "str", float: "float"}.get(kw["type"], "")
    return "|".join([
        " ".join(names),
        kw.get("action", ""),
        ty,
        nargs_field(kw.get("nargs")),
        ",".join(str(c) for c in kw.get("choices", [])),
        "1" if kw.get("required") else "0",
        default_field(kw["default"]) if "default" in kw else "",
        kw.get("dest", ""),
        kw.get("metavar", ""),
        kw.get("help") or "",
    ])


def spec_for(parser):
    """The whole parser as one spec string."""
    return ";".join(record_for(a, k) for a, k in parser["args"])


def kind_for(kw):
    """How a dest's value is printed, so both programs normalise the same way.

    `bool` for the two flag actions (which this module holds as `0`/`1` and
    CPython as `False`/`True`), `list` for anything that accumulates, `int` for
    `type=int`, `str` otherwise. The rule is read from the DECLARATION, which is
    what makes the two sides comparable without either one deciding what the
    other should have produced.
    """
    if kw.get("action") in ("store_true", "store_false"):
        return "bool"
    nargs = kw.get("nargs")
    if kw.get("action") == "append":
        return "list"
    if nargs in ("*", "+", argparse.REMAINDER):
        return "list"
    if isinstance(nargs, int) and nargs > 1:
        return "list"
    if kw.get("type") is int:
        return "int"
    return "str"


def dest_for(names, kw):
    """The dest CPython will derive, computed the way it derives it."""
    if "dest" in kw:
        return kw["dest"]
    if names and names[0][0] not in "-":
        return names[0].replace("-", "_")
    longs = [n for n in names if len(n) > 2 and n.startswith("--")]
    return (longs[0] if longs else names[0]).lstrip("-").replace("-", "_")


def py_literal(v):
    """A command-line element as a Python/Mojo string literal."""
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


HEAD_MOJO = """\
import argparse
from os._syscalls import str_alloc, str_len, str_put


def num(v):
  var b: Pointer[UInt8] = str_alloc(24)
  snprintf(b, 24, "%d", v)
  return b


def _putlit(buf, u, s):
  u = str_put(buf, u, s, str_len(s))
  memset(buf + u, 0, 1)
  return u


def say(a, b, c):
  d = str_alloc(str_len(a) + str_len(b) + str_len(c) + 2)
  u = str_put(d, 0, a, str_len(a))
  u = str_put(d, u, b, str_len(b))
  u = str_put(d, u, c, str_len(c))
  memset(d + u, 10, 1)
  memset(d + u + 1, 0, 1)
  write(1, d, u + 1)
  return 0


"""
MAIN_MOJO = """

def main(sel):
  var out: Pointer[UInt8] = str_alloc(8192)
  var err: Pointer[UInt8] = str_alloc(8192)
"""

POSTLUDE_MOJO = """\
  rc = argparse.parse(SPEC, argv, argc, out, err, DESC)
  if rc == 1:
    write(1, err, strlen(err))
    exit(0)
  if rc != 0:
    write(2, err, strlen(err))
    exit(rc)
"""


def mojo_argv_lines(parser):
    """The embedded command lines, one `if` arm per case.

    The formal entry stub takes ONE integer and the command line is not a source
    on this target at all (`bugs/FORMAL_module_state_no_storage.md`, measurement
    (4)), so the command line is compiled in and the integer selects the case.
    One image per parser therefore covers every case in the table, which is what
    makes a differential test against CPython affordable at all: an image per
    case would be twenty times the build cost.
    """
    out = []
    for i, case in enumerate(parser["cases"]):
        argv = [parser["prog"]] + case
        lit = ", ".join(py_literal(v) for v in argv)
        kw = "if" if i == 0 else "elif"
        out.append(f"  {kw} sel == {i}:\n"
                   f"    argv = [{lit}]\n"
                   f"    argc = {len(argv)}\n")
    out.append("  else:\n    return 3\n")
    return out


def mojo_print_lines(parser):
    """The canonical print for each dest, in declaration order."""
    lines = []
    for names, kw in parser["args"]:
        dest = dest_for(names, kw)
        kind = kind_for(kw)
        lines.append(f'  if argparse.has(out, "{dest}") == 0:\n'
                     f'    say("{dest}=", "None", "")\n')
        if kind == "bool":
            lines.append(f'  else:\n'
                         f'    say("{dest}=", argparse.get(out, "{dest}"), "")\n')
        elif kind == "int":
            lines.append(f'  else:\n'
                         f'    say("{dest}=", num(argparse.get_int(out, "{dest}")), "")\n')
        elif kind == "list":
            # One line: the canonical form is compared byte for byte with
            # CPython's, and CPython prints a list as `[a,b]`.
            lines.append(f'  else:\n'
                         f'    ln = argparse.count(out, "{dest}")\n'
                         f'    lb = str_alloc(ln * 64 + 4)\n'
                         f'    lu = _putlit(lb, 0, "[")\n'
                         f'    li = 0\n'
                         f'    while li < ln:\n'
                         f'      if li > 0:\n'
                         f'        lu = _putlit(lb, lu, ",")\n'
                         f'      lu = _putlit(lb, lu, argparse.get_at(out, "{dest}", li))\n'
                         f'      li = li + 1\n'
                         f'    lu = _putlit(lb, lu, "]")\n'
                         f'    say("{dest}=", lb, "")\n')
        else:
            lines.append(f'  else:\n'
                         f'    say("{dest}=", argparse.get(out, "{dest}"), "")\n')
    return lines


def mojo_source(parser):
    """The whole Mojo program for one parser."""
    parts = [HEAD_MOJO]
    parts.append(f'SPEC = "{spec_for(parser)}"\n')
    parts.append(f'DESC = "{parser["desc"]}"\n')
    parts.append(MAIN_MOJO)
    parts.extend(mojo_argv_lines(parser))
    parts.append(POSTLUDE_MOJO)
    parts.extend(mojo_print_lines(parser))
    parts.append("  return 0\n")
    return "".join(parts)


def kw_repr(kw):
    """A declaration's keywords as SOURCE, not as `repr(kw)`.

    `%r` of a dict holding a type object writes `<class 'int'>`, which is not
    valid Python — so the generated program did not even parse, and the test was
    comparing this module's answers with a SyntaxError. One spelling of the
    keywords for both halves of the generated pair is the fix.
    """
    parts = []
    for k in sorted(kw):
        v = kw[k]
        if v is int:
            parts.append('"%s": int' % k)
        elif v is str:
            parts.append('"%s": str' % k)
        elif v is argparse.REMAINDER:
            parts.append('"%s": __import__("argparse").REMAINDER' % k)
        else:
            parts.append("%r: %r" % (k, v))
    return "{%s}" % ", ".join(parts)


def py_source(parser):
    """The whole CPython program for one parser.

    Deliberately NOT a reimplementation of the canonical print: it asks
    CPython's `argparse` to parse and prints the namespace through the same
    declaration-driven rules, so the two programs agree by construction and any
    disagreement is in the parse.
    """
    lines = ["import argparse, sys\n", "\n", "SPEC = [\n"]
    for names, kw in parser["args"]:
        lines.append("    (%r, %s),\n" % (names, kw_repr(kw)))
    lines.append("]\n\n")
    lines.append("def build(ap):\n")
    for names, kw in parser["args"]:
        lines.append("    ap.add_argument(*%r, **%s)\n" % (names, kw_repr(kw)))
    lines.append("\n\n")
    lines.append("ap = argparse.ArgumentParser(prog=%r, description=%r)\n"
                 % (parser["prog"], parser["desc"]))
    lines.append("build(ap)\n")
    lines.append("sel = int(sys.argv[1])\n")
    lines.append("argv = %r\n" % [list(p) for p in parser["cases"]])
    lines.append("ns = ap.parse_args(argv[sel])\n")
    for names, kw in parser["args"]:
        dest = dest_for(names, kw)
        kind = kind_for(kw)
        v = "getattr(ns, %r)" % dest
        if kind == "bool":
            body = '"%s=" + ("1" if %s else "0")' % (dest, v)
        elif kind == "int":
            body = ('"%s=" + ("None" if %s is None else str(%s))'
                    % (dest, v, v))
        elif kind == "list":
            body = ('"%s=" + ("None" if %s is None else '
                    '"[" + ",".join(str(x) for x in %s) + "]")'
                    % (dest, v, v))
        else:
            body = '"%s=" + ("None" if %s is None else str(%s))' % (dest, v, v)
        lines.append('print(%s)\n' % body)
    return "".join(lines)


# ── Running both sides ───────────────────────────────────────────────────────

def run_mojo(root, parser, case_index, worker=0):
    """Build and run the arm64 image for one case. Its CompletedProcess.

    Builds the whole parser's image — the command lines are compiled in and the
    entry argument selects one — and runs it once. A build that did not succeed
    raises, so no case can be compared against the output of a program that was
    never produced.
    """
    src = os.path.join(root, parser["name"] + ".mojo")
    with open(src, "w") as f:
        f.write(mojo_source(parser))
    out = os.path.join(root, "%s.%d.aout" % (parser["name"], case_index))
    env = dict(os.environ, GMOJO_HOME=_worker_cas(worker))
    built = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         "-n", str(case_index), "-o", out, src],
        cwd=root, capture_output=True, text=True, timeout=900, env=env)
    check(built.returncode == 0,
          f"{parser['name']} case {case_index}: build failed: "
          f"{(built.stderr or built.stdout).strip()[-600:]}")
    check(os.path.isfile(out), f"{parser['name']}: no executable at {out}")
    ran = subprocess.run([out], capture_output=True, text=True, timeout=60)
    return ran


def run_cpython(root, parser, case_index):
    """CPython's own `argparse` on the same declaration and command line."""
    src = os.path.join(root, parser["name"] + "_py.py")
    with open(src, "w") as f:
        f.write(py_source(parser))
    return subprocess.run([sys.executable, src, str(case_index)],
                          capture_output=True, text=True, timeout=60)


def compare(case_label, want, got):
    """Assert the image and CPython agree on all three observable answers."""
    check(want.returncode == got.returncode,
          f"{case_label}: exit status {got.returncode}, CPython's is "
          f"{want.returncode}.\n  image stderr: {got.stderr!r}\n"
          f"  cpython stderr: {want.stderr!r}")
    check(want.stdout == got.stdout,
          f"{case_label}: stdout differs.\n  image:   {got.stdout!r}\n"
          f"  cpython: {want.stdout!r}")
    check(want.stderr == got.stderr,
          f"{case_label}: stderr differs (this is the usage line and the "
          f"error message).\n  image:   {got.stderr!r}\n"
          f"  cpython: {want.stderr!r}")


# ── Resolution and exports ───────────────────────────────────────────────────

def test_argparse_resolves_to_the_module_source(tmp, _shared):
    """`import argparse` finds `formal/hostmods/argparse.mojo`, in the
    resolver's own order, from the root and from a subdirectory.

    Pass 1 of `resolve_module_path` is Mojo source in a search root, and it wins
    over the host-module list — so this is the assertion that says the module is
    reachable at all. The location itself is asserted, not just the resolution:
    a module source back at the repository root resolves from here too, and the
    whole point of `formal/hostmods/` is that NOTHING ELSE in the tree can see
    it. `test_hostmods_are_invisible_to_every_other_resolver` in
    `test_formal_link_accounting.py` is that other half.
    """
    from formal.imports import HOST_MODELLED, resolve_module_path
    at_root = resolve_module_path("argparse",
                                  relative_to=os.path.join(HERE, "t1.mojo"))
    check(at_root == ARGPARSE_MODULE,
          f"`import argparse` from the repository root did not resolve to "
          f"{ARGPARSE_MODULE}, got {at_root!r}")
    nested = os.path.join(HERE, "tools", "formal_sweep.py")
    check(resolve_module_path("argparse", relative_to=nested) == ARGPARSE_MODULE,
          "`import argparse` from tools/ did not resolve to the module source "
          "— the hostmods root is appended to every file's search roots")
    check("argparse" not in HOST_MODELLED,
          "argparse is still in HOST_MODELLED: a Mojo source wins over that "
          "set, so the entry no longer describes anything the build does")


def test_every_declared_name_is_exported(tmp, _shared):
    """Every public function in argparse.mojo reaches a dylib's export table.

    The export rule (`doc/ABI.md`, via `reflect.collect_exports_src`) is what
    `exit` loses in `sys`, so a name added here without checking it would
    produce a module that builds and cannot be called. The assertion is over the
    module's OWN declaration list, read from its source, so it fails on the name
    rather than on a count.
    """
    sys.path.insert(0, HERE)
    import fire_compiler as F
    with open(ARGPARSE_MODULE) as f:
        stmts = F.Parser(F.py_tokenize(f.read())).parse_module()
    declared = {s.name for s in stmts
                if isinstance(s, F.FunctionDef) and not s.name.startswith("_")}
    check(declared, "argparse.mojo declares no public function")
    root = os.path.join(tmp, "probe")
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "probe.mojo")
    with open(path, "w") as f:
        f.write('import argparse\n\ndef main():\n  return 0\n')
    out = os.path.join(root, "probe.aout")
    built = run_fire(["build", "--formal", "--no-prove", "-o", out, path],
                     cwd=root)
    check(built.returncode == 0,
          f"a program importing argparse did not build: "
          f"{(built.stderr or built.stdout).strip()[-600:]}")
    import glob
    found = sorted(glob.glob(os.path.join(
        _CAS_HOME, "cas", "formal-imports", "arm64", "argparse.*.dylib")))
    check(bool(found), f"no argparse module dylib built under {_CAS_HOME}")
    with open(found[-1] + ".manifest.json") as f:
        payload = json.load(f)
    exported = {e["name"] for e in payload.get("exports") or []}
    missing = sorted(declared - exported)
    check(not missing,
          f"argparse.mojo declares {missing} but the export table does not "
          "advertise it: a name doc/ABI.md's rule excludes is a module nothing "
          "can call")


# ── The module is a program too ──────────────────────────────────────────────

def test_the_module_builds_on_its_own(tmp, _shared):
    """`fire.py build --formal` of argparse.mojo itself exits 0.

    Every other assertion in this file builds a program that IMPORTS the
    module, so the module is only ever reached as somebody else's dependency,
    and a diagnostic raised about a line inside it arrives as a failure of the
    importing program instead of as a statement about the file that has the
    problem. That is the whole reason a refusal lived here as long as it did: 36
    of the 44 files in the sweep that import `argparse` were refused as
    `codegen/dependency`, and every one of them carried the same message, whose
    subject is a comparison inside `_lookup` — a module none of the 36 had
    anything to do with.

        So: the module as a translation unit, with nothing importing it, on the
        default backend (arm64, which is the target the corpus above is run on).

        x86-64 is not asserted HERE and does not need to be: the per-module,
        per-backend table is `test_formal_hostmods_census.py`, which builds all
        sixteen host modules on both backends and is where a row about one
        module belongs — so a red about this module's arm64 build and a red
        about this module's x86-64 build stay two different failures with two
        different subjects.  (This docstring used to say x86-64 was not
        measured because the build "stops earlier, in `os/_syscalls.mojo`'s own
        dylib ('main executable failed strict validation')".  That was true when
        it was written and is no longer: the dylib emitter's defect is fixed,
        every module in the table builds on x86-64 but two, and argparse is one
        of the fourteen that do.)


    The build is a cold one: this file points GMOJO_HOME at a private CAS per
    process, so a dylib published by an earlier run cannot answer for this
    module's source (bugs/FORMAL_sweep_cache_ignores_imports.md is the
    measurement of what happens when something keyed on the importer is served
    from a cache that does not know about it).
    """
    out = os.path.join(tmp, "argparse_standalone.aout")
    built = run_fire(["build", "--formal", "--no-prove", "-o", out,
                      ARGPARSE_MODULE])
    check(built.returncode == 0,
          f"argparse.mojo does not build as a program, so nothing that imports "
          f"it can either: "
          f"{(built.stderr or built.stdout).strip()[-600:]}")
    check(os.path.isfile(out),
          f"the build reported success and wrote no image at {out}")


# ── The parse is CPython's ────────────────────────────────────────────────────

def test_the_parse_matches_cpython(tmp, _shared):
    """Every case in PARSERS: the arm64 image and CPython's argparse agree.

    One table drives both programs. The image is BUILT AND RUN, and its stdout,
    stderr and exit status are compared with CPython's own `argparse` on the same
    declaration and the same command line — so this covers values, defaults,
    abbreviations, `--opt=value`, combined short flags, the `--` separator, every
    nargs shape, `choices`, type errors, required errors, unrecognized
    arguments, the usage line, the error wording and the exit status 2.

    arm64 only. The reason this file gives for that used to be "a module dylib
    that calls into the C library produces an image the loader refuses under
    `--backend=x86_64`", and it was false — see the top of
    `formal/hostmods/os/__init__.mojo`, which is where the measurement is. What
    is true is narrower and is left as it stands: this file builds ONE
    architecture, in `build_and_run` and in the CAS path it reads, so making it
    cover both is a change to this file's shape rather than a skip to remove.
    """
    if platform.machine() not in ("arm64", "aarch64", "x86_64"):
        print("        SKIP: no Darwin host to run the image on")
        return
    root = os.path.join(tmp, "diff")
    os.makedirs(root, exist_ok=True)

    jobs = []
    for parser in PARSERS:
        for i in range(len(parser["cases"])):
            jobs.append((parser, i, len(jobs) % 4))

    def one(job):
        parser, i, worker = job
        argv = " ".join(repr(a) for a in parser["cases"][i])
        label = f"{parser['name']}[{i}] argv={argv}"
        want = run_cpython(root, parser, i)
        got = run_mojo(root, parser, i, worker)
        return label, want, got

    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for label, want, got in pool.map(one, jobs):
            try:
                compare(label, want, got)
            except TestFailure as e:
                failures.append(str(e))
    check(not failures, f"{len(failures)} of {len(jobs)} cases differ from "
                        "CPython:\n  " + "\n  ".join(failures))
    print(f"        {len(jobs)} cases: {len(PARSERS)} parsers, each built as "
          f"an arm64 image and run against CPython's own argparse")


# ── Refusals and limits, pinned as measurements ──────────────────────────────

FLOAT_SPEC = "--limit-gb|store|float"
REMAINDER_SPEC = "--limit-gb|store|float||55.0\ncmd|*"

REFUSALS = [
    ("type=float", FLOAT_SPEC, "--limit-gb", "2.5"),
    ("an nargs that is not one of the subset's", "--x|store||j", "--x", "a"),
    ("a type that is not str or int", "--x|store|complex", "--x", "a"),
    ("a declared -h", "-h|store_true", "-h", None),
    ("a declared --help", "--help|store_true", "--help", None),
]

REFUSAL_PROGRAM = """\
import argparse
from os._syscalls import str_alloc

SPEC = "%s"

def main():
  argv = ["demo", "%s"%s]
  argc = %d
  var out: Pointer[UInt8] = str_alloc(8192)
  var err: Pointer[UInt8] = str_alloc(8192)
  rc = argparse.parse(SPEC, argv, argc, out, err, "")
  printf("rc=%%d\\n", rc)
  printf("msg=%%s", err)
  return 0
"""


def test_a_refused_spec_is_refused_with_a_reason(tmp, _shared):
    """Each unsupported construct is declined, not approximated.

    The one that matters most is `type=float`, because the alternative is a
    plausible wrong answer: `2.5` as a literal is the integer 2 on this target
    (measured, and the reason is in `formal/model.py`'s `_FLOAT_SCALARS`), so an
    `argparse` that accepted `--limit-gb 2.5` and answered 2 would be computing
    something other than what its name says. `tools/memcap.py` wants exactly
    this and is refused for it.

    The other four are CPython declarations this subset does not implement, and
    each is refused at parse time with the reason in `err` rather than answered
    by a guess.
    """
    root = os.path.join(tmp, "refuse")
    os.makedirs(root, exist_ok=True)
    for label, spec, flag, value in REFUSALS:
        args = ["demo", flag] + ([value] if value is not None else [])
        src = os.path.join(root, "r.mojo")
        with open(src, "w") as f:
            f.write(REFUSAL_PROGRAM % (spec, flag,
                                       (', "%s"' % value) if value else "",
                                       len(args)))
        out = os.path.join(root, "r.aout")
        built = run_fire(["build", "--formal", "--no-prove", "-o", out, src],
                         cwd=root)
        check(built.returncode == 0,
              f"{label}: the program did not build: "
              f"{(built.stderr or built.stdout).strip()[-400:]}")
        ran = subprocess.run([out], capture_output=True, text=True, timeout=60)
        check("rc=3" in ran.stdout,
              f"{label}: parse returned {ran.stdout.splitlines()[:1]}, "
              f"expected the refusal status 3. stdout: {ran.stdout!r}")
        check(len(ran.stdout.split("msg=", 1)[-1].strip()) > 10,
              f"{label}: the refusal carries no reason: {ran.stdout!r}")


UNDERSCORE_PROGRAM = """\
import argparse
from os._syscalls import str_alloc

SPEC = "--n|store|int"

def main():
  argv = ["demo", "--n", "%s"]
  argc = 3
  var out: Pointer[UInt8] = str_alloc(8192)
  var err: Pointer[UInt8] = str_alloc(8192)
  rc = argparse.parse(SPEC, argv, argc, out, err, "")
  printf("rc=%%d\\n", rc)
  printf("msg=%%s", err)
  return 0
"""


def test_an_underscore_in_an_int_is_refused(tmp, _shared):
    """`--n 1_0` is refused rather than read as 10.

    CPython's `int("1_0")` is 10. Reading it here with `atoi` would be 1 — a
    different number with nothing downstream able to tell — so the value is
    refused and the message says why. Pinned as a measurement because it is the
    kind of difference a reader of `get_int` would otherwise assume is a bug in
    the caller rather than a decision.
    """
    root = os.path.join(tmp, "uscore")
    os.makedirs(root, exist_ok=True)
    src = os.path.join(root, "u.mojo")
    with open(src, "w") as f:
        f.write(UNDERSCORE_PROGRAM % "1_0")
    out = os.path.join(root, "u.aout")
    built = run_fire(["build", "--formal", "--no-prove", "-o", out, src],
                     cwd=root)
    check(built.returncode == 0,
          f"build failed: {(built.stderr or built.stdout).strip()[-400:]}")
    ran = subprocess.run([out], capture_output=True, text=True, timeout=60)
    check("rc=2" in ran.stdout,
          f"`--n 1_0` returned {ran.stdout.splitlines()[:1]}, expected the "
          f"error status 2: {ran.stdout!r}")
    check("invalid int value: '1_0'" in ran.stdout,
          f"the message does not name the value it refused: {ran.stdout!r}")


BASENAME_PROGRAM = """\
import argparse
from os._syscalls import str_alloc

SPEC = "-v|store_true"

def main():
  argv = ["/usr/local/bin/tool", "--bogus"]
  argc = 2
  var out: Pointer[UInt8] = str_alloc(8192)
  var err: Pointer[UInt8] = str_alloc(8192)
  rc = argparse.parse(SPEC, argv, argc, out, err, "")
  write(2, err, strlen(err))
  return 0
"""


def test_prog_is_the_basename_of_argv0(tmp, _shared):
    """`prog` is `basename(argv[0])`, which is what CPython derives it from.

    The whole of CPython's `prog` default, on the one target that has a command
    line at all. With `argv[0]` supplied by the caller this is exact, and it is
    what makes every error message in the table above the message CPython
    prints for the same program.
    """
    root = os.path.join(tmp, "prog")
    os.makedirs(root, exist_ok=True)
    src = os.path.join(root, "p.mojo")
    with open(src, "w") as f:
        f.write(BASENAME_PROGRAM)
    out = os.path.join(root, "p.aout")
    built = run_fire(["build", "--formal", "--no-prove", "-o", out, src],
                     cwd=root)
    check(built.returncode == 0,
          f"build failed: {(built.stderr or built.stdout).strip()[-400:]}")
    ran = subprocess.run([out], capture_output=True, text=True, timeout=60)
    check(ran.stderr.startswith("usage: tool [-h] [-v]"),
          f"the usage line is {ran.stderr.splitlines()[:1]}, which does not "
          "name the program `tool`")


def test_the_module_is_the_one_the_sweep_resolves(tmp, _shared):
    """The sweep now classifies a refusal in one of the eighteen files as a
    codegen finding rather than as the host-import refusal it was.

    `tools/formal_sweep.py`'s classifier treats a message that quotes a module
    the file imports as an import failure whatever the wording. That stopped
    being right the moment `argparse` got a source in the tree — the module
    exists, the build resolved it, and what a file importing it is refused for is
    a construct. Called through `classify` with the swept file's PATH, because
    the path is what the resolver needs and what the sweep passes.
    """
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import formal_sweep as S
    path = os.path.join(HERE, "tools", "memcap.py")
    with open(path) as f:
        source = f.read()
    detail = ("build: main: 'argparse' is imported from `argparse`, so it is a "
              "module-level name of another module. This path compiles an "
              "import into a dylib, and a module-level name is not exported "
              "as a word — there is no storage for it here")
    cls, _ = S.classify(False, detail, source=source, path=path)
    check(cls == S.CLASS_CODEGEN,
          f"an argparse refusal is classified {cls!r}; with the module in the "
          "tree it is a codegen finding, not a fact about the target")


TESTS = [
    ("`import argparse` resolves to the module source",
     test_argparse_resolves_to_the_module_source),
    ("every declared name is exported", test_every_declared_name_is_exported),
    ("the module builds on its own",
     test_the_module_builds_on_its_own),
    ("the parse matches CPython, case for case",
     test_the_parse_matches_cpython),
    ("an unsupported spec is refused with a reason",
     test_a_refused_spec_is_refused_with_a_reason),
    ("an underscore in an int is refused, not truncated",
     test_an_underscore_in_an_int_is_refused),
    ("prog is the basename of argv[0]",
     test_prog_is_the_basename_of_argv0),
    ("the sweep classifies an argparse refusal as codegen",
     test_the_module_is_the_one_the_sweep_resolves),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    passed = failed = 0
    import shutil
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, fn in TESTS:
                try:
                    fn(tmpdir, None)
                except TestFailure as e:
                    failed += 1
                    print(f"  FAIL  {name}\n        {e}")
                    continue
                except Exception as e:          # unexpected: report, do not mask
                    failed += 1
                    print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                    if args.verbose:
                        import traceback
                        traceback.print_exc()
                    continue
                passed += 1
                print(f"  PASS  {name}")
    finally:
        shutil.rmtree(_CAS_HOME, ignore_errors=True)
    print(f"\nformal argparse: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
