#!/usr/bin/env python3
"""Cross-module/link correctness on the formal path: what a call ACROSS a
dylib boundary is allowed to mean.

`test_formal_imports.py` covers WHICH module a name resolves to and
`test_formal_run.py` covers what one image can lower. Neither reaches the
boundary itself, and the boundary is where every one of these five constructs
either did the right thing or produced something that looked fine:

  1. `from m import f as g` — the alias is a property of the IMPORTING file, and
     the export table is keyed by the DEFINING name. Looking the callee up by
     the local spelling found nothing, and the image bound a symbol no library
     defines. (`FORMAL_from_import_alias_dangles_the_call`, fixed.)
  2. a RELATIVE import — `from ._helper import f`. It USED to be the shape
     whose ABI prefix began with an underscore (`abi_module_name('._helper')`
     was `__helper`), so every symbol it exported began with one and the
     sweep's dyld probe stripped the "leading underscore" a second time and
     reported a load failure for an image that loads. It no longer is: a
     relative import carries its parent's identity, so `._helper` inside `relpkg`
     is the module `relpkg._helper` and binds `relpkg__helper_twice_…`
     (`formal/build.py`'s `own_module_identity`). The probe defect is fixed
     (`tools/formal_sweep.py`'s `_exports` never normalises, and its static arm
     uses `_macho_symbol`), and the end-to-end fixture that reproduced it lives
     in `test_formal_sweep.py::TestDyldProbe`
     (`test_a_bind_name_that_itself_begins_with_an_underscore_resolves`), on
     the shape where a relative import's prefix does begin with an underscore.
     The cases below assert BEHAVIOUR rather than a spelling, which is why they
     kept passing across the change — and the behaviour is the claim.
  3. a DEFAULT argument across the boundary. The callee is not in the importing
     image's function registry, so nothing bound the arguments: the omitted
     register kept whatever the caller last put there, and `need_two(1)` read a
     stack address where the callee's own default says 511. A silently wrong
     ARGUMENT, which is the outcome this boundary exists to prevent.
     (`FORMAL_default_argument_not_applied_across_a_dylib`, fixed.)
  4. a STRUCT from a `--link-dylib` library. Its methods crossed the boundary
     and its DECLARATION did not, so `b.n = 4` was refused with a repair the
     reader cannot follow. (`FORMAL_link_dylib_imported_struct_field`,
     fixed.)
  5. `S()` on a struct whose `__init__` takes no required parameter — a
     construction, not a call, and the one construct whose lowering a dylib
     boundary does not change at all. It is here because it is the CONTROL for
     (3): the same disagreement with the language, reached without any module
     involved. (`FORMAL_zero_arg_init_not_inlined`, fixed.)

Every case below BUILDS the arm64 image, EXECUTES it, and compares its output
and exit status with CPython running the SAME program. A refusal is asserted
only where CPython also refuses, with the words it refuses in; the two
directions both matter, because "the image ran and printed the right thing" and
"the build refused" are different verdicts and only one of them is coverage.

Invoked directly:
    python3 test_formal_cross_module.py [-v]
"""
import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# The driver and the pass/fail helper live in the dylib suite; imported rather
# than copied so a fix to one cannot leave a second, quietly different one.
from test_formal_dylib import TestFailure, check, run_fire

# Module dylibs are cached by content and written per architecture, so a test
# that looks for one has to ask for the architecture it built — and it must not
# read another tree's libraries, or a case can pass on a dylib it did not
# build. This file therefore gets a CAS of its OWN, set before `cas` is ever
# imported. `test_formal_imports.py` says more about why a shared one is not
# safe under a parallel bucket; the short form is that it deletes the whole
# module-dylib directory between cases.
_CAS_HOME = tempfile.mkdtemp(prefix="formal_cross_module_cas_")
os.environ["GMOJO_HOME"] = _CAS_HOME
CAS_IMPORTS_ROOT = os.path.join(_CAS_HOME, "cas", "formal-imports")


def _drop_cas_home():
    shutil.rmtree(_CAS_HOME, ignore_errors=True)


def fresh_cas():
    """Empty the module-dylib cache, so no case can pass on a stale library."""
    shutil.rmtree(CAS_IMPORTS_ROOT, ignore_errors=True)


def write_tree(root, files):
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        with open(path, "w") as f:
            f.write(text)


def build(root, name, expect_ok=True, arch=None, extra=()):
    """`fire.py build --formal --no-prove -o <root>/<name> <root>/<name>.mojo`.

    `name` carries the extension of the artifact (`prog.aout`), which is also
    what selects the source. `extra` is for `--link-dylib`, `arch` for
    `--backend=`.
    """
    out = os.path.join(root, name)
    src = os.path.join(root, name[:-len(".aout")] + ".mojo")
    argv = ["build", "--formal", "--no-prove", "-o", out]
    if arch:
        argv.append(f"--backend={arch}")
    argv += list(extra) + [src]
    result = run_fire(argv, cwd=root)
    if expect_ok:
        check(result.returncode == 0,
              f"build failed: {(result.stderr or result.stdout).strip()[-500:]}")
        check(os.path.isfile(out), f"no executable written at {out}")
    return result, out


def build_dylib(root, name, sources, expect_ok=True):
    out = os.path.join(root, name)
    result = run_fire(["dylib", "--formal", "--no-prove", "-o", out]
                      + [os.path.join(root, s) for s in sources], cwd=root)
    if expect_ok:
        check(result.returncode == 0,
              f"`fire.py dylib` failed: "
              f"{(result.stderr or result.stdout).strip()[-500:]}")
        check(os.path.isfile(out), f"no dylib written at {out}")
    return result, out


def run(out):
    r = subprocess.run([out], capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stderr or r.stdout)


def refuses(result, needle):
    """The build failed, and its message contains `needle`.

    Asserting the WORDS and not merely a non-zero exit is the point: this
    backend's refusals are its product, and a reader who is sent after a
    construct that is not in their file has been handed a message that is false
    about the program in front of them.
    """
    check(result.returncode != 0,
          "the build SUCCEEDED and was expected to refuse")
    text = (result.stderr or result.stdout)
    check(needle in text,
          f"refused, but not with the expected words {needle!r}:\n"
          f"{text.strip()[-800:]}")


# The mechanical translation from this path's spelling to CPython's. Four
# substitutions and nothing else, because a paraphrase of the program would
# make every comparison in this file a comparison against a DIFFERENT program:
#
#   `struct S:`            → `class S:`
#   `def __init__(out self`→ `def __init__(self`     (Mojo's receiver spelling)
#   `def f(self, i: Int) -> Int:` → `def f(self, i):` (annotations, both sides)
#   `var n: Int`           → `n = 0`                  (a Mojo FIELD is not a
#                                                        Python class attribute
#                                                        statement, and there is
#                                                        nothing else it could be)
#   `var z = Z()`          → `z = Z()`                (a local `var` is a plain
#                                                        assignment with a keyword
#                                                        CPython has no word for)
#   `from ._helper import` → `from _helper import`    (the generated `.py` is a
#                                                        MODULE, not a package
#                                                        member, so a relative
#                                                        import has no parent)
#
# `printf` is NOT translated: a shim is prepended to the PROGRAM only, so the
# format string and the arguments are the ones the source wrote rather than a
# re-spelling of them. The modules get no shim, because they are imported for
# their declarations and print nothing.
_DEF_RE = re.compile(r"(def\s+\w+\s*\()([^)]*)(\))([^:\n]*):")


def _param(param):
    """`i: Int` → `i`, `a: Int = 8` → `a = 8`, `*rest` → `*rest`.

    The annotation is cut at the first `=` so a DEFAULT survives, which is the
    whole point of the cases below: `Z.__init__(a=8, b=9)` is the program whose
    zero-argument construction has to produce 8 and 9, and a translation that
    dropped the defaults would be asserting something else entirely.
    """
    head, eq, default = param.partition("=")
    return head.split(":")[0].strip() + eq + default.strip()


def _def_params(match):
    """`def f(self, i: Int) -> Int:` → `def f(self, i):`.

    The return annotation (group 4) is dropped by the same pattern that finds
    the parameter list, so a `->` inside the parentheses cannot confuse it.
    """
    params = ", ".join(_param(p) for p in match.group(2).split(",") if p.strip())
    return f"{match.group(1)}{params}{match.group(3)}:"


def _as_python(text):
    """One Mojo source, mechanically, as the Python CPython would accept."""
    text = text.replace("struct ", "class ")
    text = text.replace("(out self", "(self")
    text = _DEF_RE.sub(_def_params, text)
    text = re.sub(r"^([ \t]*)var[ \t]+(\w+)[ \t]*:.*$", r"\1\2 = 0", text,
                  flags=re.M)
    text = re.sub(r"^([ \t]*)var[ \t]+(\w+)[ \t]*=", r"\1\2 =", text,
                  flags=re.M)
    text = re.sub(r"^([ \t]*)from[ \t]+\.+[ \t]*", r"\1from ", text,
                  flags=re.M)
    return text


def cpython(root, name, main_arg="0", preamble=""):
    """Run the same program under CPython and return `(exit, stdout)`.

    EVERY `.mojo` under `root` is translated alongside itself, not just the
    program: the cases here are mostly `from <module> import …`, and a `.py`
    that only holds the program would import nothing and fail for a reason that
    has nothing to do with what is being tested. The module's own translation
    goes through the same function, so both sides of the boundary are the same
    declaration read by two compilers.

    `preamble` is text inserted before the program, and it exists for exactly
    one case: a program that gets a module's names through `--link-dylib`
    instead of an import. CPython has no such boundary, so the names have to
    come from an import there, and saying so is more honest than quietly
    rewriting the program under test.

    `main`'s return value is the exit status, which is what the formal path's
    startup stub does with it — so the two agree on the channel as well as the
    text, and a case can assert "this program is supposed to fail" without a
    second mechanism for saying so.
    """
    # `root` AND ITS PARENT: a two-level relative import names a module one
    # directory up, and after the dots are stripped that is an ordinary import
    # of a name the parent directory holds. Both are put on `PYTHONPATH` below,
    # so the two-level case is answered by the same translation as the
    # one-level one rather than by a special case.
    roots = [root, os.path.dirname(root)]
    for base in roots:
        if not base or not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for f in filenames:
                if not f.endswith(".mojo"):
                    continue
                src = os.path.join(dirpath, f)
                with open(src) as fh:
                    body = _as_python(fh.read())
                with open(src[:-len(".mojo")] + ".py", "w") as fh:
                    fh.write(body)
    shim = ('import sys\n\n\n'
            'def printf(fmt, *a):\n'
            '    sys.stdout.write((fmt % a) if a else fmt)\n\n\n')
    path = os.path.join(root, name[:-len(".aout")] + "_cp.py")
    with open(os.path.join(root, name[:-len(".aout")] + ".mojo")) as fh:
        text = _as_python(fh.read())
    with open(path, "w") as fh:
        fh.write(shim + preamble + text + f"\n\nsys.exit(main({main_arg}))\n")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        r for r in (root, os.path.dirname(root)) if r and os.path.isdir(r))
    r = subprocess.run([sys.executable, path], capture_output=True,
                       text=True, timeout=120, cwd=root, env=env)
    check(r.returncode in (0, 1),
          f"CPython itself failed on {path}: {r.stderr.strip()[-400:]}")
    return r.returncode, r.stdout


def agrees_with_cpython(tmpdir, case, root, name, expect_exit=None,
                        extra=(), preamble=""):
    """Build, run, and require the image to match CPython on both channels.

    The comparison is CPython's, never a table: a value written down beside the
    test is a second answer to the same question, and it goes stale exactly
    when the compiler changes.
    """
    result, out = build(root, name, extra=extra)
    rc, text = run(out)
    want_rc, want_out = cpython(root, name, preamble=preamble)
    check(text == want_out,
          f"{case}: the image printed\n  {text!r}\nCPython printed\n"
          f"  {want_out!r}")
    check(rc == want_rc,
          f"{case}: the image exited {rc}, CPython exited {want_rc}")
    if expect_exit is not None:
        check(rc == expect_exit,
              f"{case}: expected exit {expect_exit}, image {rc}, "
              f"CPython {want_rc}")
    return text, rc


# ── (1) `from m import f as g` ───────────────────────────────────────────────

# `need_two`'s default is 511 and `need_one` takes one argument and returns it,
# so a call that bound the wrong function, or dropped an argument, cannot
# produce these four numbers by accident.
DEF_LIB = """\
def need_two(a, b=511):
    return b


def need_one(a):
    return a


def no_args():
    return 4242
"""

ALIAS_PROG = """\
from deflib import need_two as nt, need_one as no, no_args as na

def main(k):
    printf("alias-default=%d@", nt(1))
    printf("alias-explicit=%d@", nt(1, 77))
    printf("alias-one=%d@", no(5))
    printf("alias-noargs=%d@@", na())
    return 0
"""


def test_a_from_import_alias_calls_the_function_it_stands_for(tmpdir, _):
    """`from m import f as g`, and `g` calls `f`.

    This is the whole of bug (1). The local spelling is what every call site
    uses and the export table is keyed by the defining name, so the lookup
    missed and the image bound `g` itself — which the link audit refused with
    two unbound symbols and no idea why. Same two names WITHOUT the alias built,
    linked and ran, so it was the alias and nothing else.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "alias")
    os.makedirs(root)
    write_tree(root, {"deflib.mojo": DEF_LIB, "prog.mojo": ALIAS_PROG})
    text, rc = agrees_with_cpython(tmpdir, "from-import alias", root,
                                   "prog.aout", expect_exit=0)
    check("alias-default=511@" in text,
          f"the defaulted argument did not arrive: {text!r}")


def test_a_library_that_CALLS_its_own_import_alias_binds_the_defining_name(
        tmpdir, _):
    """The alias is a property of the file that WRITES it, so the module that
    calls it has to bind the DEFINING name — and that module is a LIBRARY.

    The case above is the other direction: the alias is written by the program,
    whose emitters have always been handed `import_bindings`. This one is
    written by a module that is itself compiled as a dylib, and
    `compile_formal_dylib` did not hand its emitters that table — so the call
    bound `aliased` itself and the library's own bind audit refused the image
    with a message about the LINK LINE, where the construct is a call the source
    had already resolved:

        build: mid.mojo: the library would bind 1 symbol(s) that nothing
        provides, so it could not be loaded: aliased

    Three files because the shape needs a boundary on BOTH sides of the alias:
    `leaf` defines, `mid` imports under an alias and calls it, `prog` imports
    `mid`. A two-file tree would pass with the alias handling on `prog`'s side
    alone, which is what made this invisible.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "alias_in_library")
    os.makedirs(root)
    write_tree(root, {
        "leaf.mojo": "def base(a):\n    return a + 20\n",
        "mid.mojo": "from leaf import base as aliased\n\n\n"
                    "def marker(a):\n    return aliased(a)\n",
        # A LITERAL argument, not `k`: the formal entry stub hands `main` its
        # `test_input` (10 by default) while `cpython()` here calls `main(0)`,
        # so a case that reads its parameter is comparing the two harnesses'
        # entry values rather than the alias. Every other alias case in this
        # group passes constants for the same reason.
        "prog.mojo": "from mid import marker\n\n\n"
                     "def main(k):\n    printf(\"mid-alias=%d@@\", marker(10))\n"
                     "    return 0\n",
    })
    text, rc = agrees_with_cpython(tmpdir, "alias inside a library", root,
                                   "prog.aout", expect_exit=0)
    check("mid-alias=30@" in text,
          f"the aliased call inside the library did not bind leaf's function: "
          f"{text!r}")


def test_an_alias_of_a_non_exported_name_is_refused_by_name(tmpdir, _):
    """`from m import _private as p`, and `p()` is refused naming the module.

    An alias must not make a name exposable that `doc/ABI.md`'s export rule
    kept out of the boundary — the alias is a property of the importing file,
    not of the library. The alternative is a build that passes and an image
    that dies in dyld, which is the outcome this mechanism exists to prevent.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "alias_private")
    os.makedirs(root)
    write_tree(root, {
        "privlib.mojo": "def _secret(a):\n    return a + 1000\n\n\n"
                        "def visible(a):\n    return a + 1\n",
        "prog.mojo": "from privlib import _secret as p\n\n\n"
                     "def main(k):\n    printf(\"%d@@\", p(1))\n    return 0\n",
    })
    result, _out = build(root, "prog.aout", expect_ok=False)
    refuses(result, "nor any other library on this image's link line exports "
                    "`_secret`")


def test_a_plain_from_import_that_cannot_be_bound_is_still_the_audit_s(tmpdir, _):
    """The same shape WITHOUT an alias keeps the bind audit's own message.

    The guard on the alias refusal: `from m import f` that cannot be resolved is
    the long-standing "nothing on this link line provides it" case and the bind
    audit still reports it. A new, second message for one condition would send
    the reader after a construct that is not the problem.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "plain_missing")
    os.makedirs(root)
    write_tree(root, {
        "misslib.mojo": "def other(a):\n    return a\n",
        "prog.mojo": "from misslib import absent as present\n\n\n"
                     "def main(k):\n    printf(\"%d@@\", present(1))\n"
                     "    return 0\n",
    })
    # `present` IS an alias here, so it must be refused by the alias message;
    # this is the control that the alias table is not consulted for a name it
    # does not carry. A program with no import at all reaches the audit.
    result, _out = build(root, "prog.aout", expect_ok=False)
    refuses(result, "nor any other library on this image's link line exports "
                    "`absent`")


# ── (2) a RELATIVE import, whose symbols begin with an underscore ───────────

REL_LIB = """\
def twice(a):
    return a + a
"""


def test_a_relative_import_resolves_and_runs(tmpdir, _):
    """`from ._helper import twice`, called as `twice(21)`.

    A relative import's ABI prefix begins with an underscore, so every symbol
    it exports does too. That is the shape the sweep's dyld probe got wrong —
    it stripped "the leading underscore" off the bind name a second time and
    reported a load failure for an image that loads — and it is also the shape
    every package in `formal/hostmods/` is written in, so it is worth running
    rather than only sweeping.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "relpkg")
    write_tree(root, {
        "relpkg/_helper.mojo": REL_LIB,
        "relpkg/__init__.mojo": "from ._helper import twice\n\n\n"
                                "def main(k):\n"
                                "    printf(\"rel=%d@@\", twice(21))\n"
                                "    return 0\n",
    })
    text, rc = agrees_with_cpython(tmpdir, "relative import",
                                   os.path.join(root, "relpkg"),
                                   "__init__.aout", expect_exit=0)
    check("rel=42@" in text, f"the relative call did not arrive: {text!r}")


def test_a_two_level_relative_import_resolves_and_runs(tmpdir, _):
    """`from .._helper import twice` from `pkg/sub/__init__.mojo`.

    The two-level spelling is the one the two `os` hosts use, and it is a
    different ABI prefix from the one-level one (`___helper` vs `__helper`), so
    the two cannot be the same library by accident — which is what makes this
    pair worth having rather than one case.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "relpkg2")
    write_tree(root, {
        "relpkg2/_helper.mojo": REL_LIB,
        "relpkg2/sub/__init__.mojo": "from .._helper import twice\n\n\n"
                                     "def main(k):\n"
                                     "    printf(\"rel2=%d@@\", twice(11))\n"
                                     "    return 0\n",
    })
    text, rc = agrees_with_cpython(tmpdir, "two-level relative import",
                                   os.path.join(root, "relpkg2", "sub"),
                                   "__init__.aout", expect_exit=0)
    check("rel2=22@" in text, f"the two-level relative call missed: {text!r}")


def test_a_relative_import_behind_an_alias_resolves_and_runs(tmpdir, _):
    """The two halves together: `from ._helper import twice as t`.

    Neither is interesting alone and both together were broken twice over: the
    alias had nothing to resolve to, and the prefix that would have resolved it
    begins with an underscore.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "relalias")
    write_tree(root, {
        "relalias/_helper.mojo": REL_LIB,
        "relalias/__init__.mojo": "from ._helper import twice as t\n\n\n"
                                  "def main(k):\n"
                                  "    printf(\"relalias=%d@@\", t(50))\n"
                                  "    return 0\n",
    })
    text, rc = agrees_with_cpython(tmpdir, "relative import + alias",
                                   os.path.join(root, "relalias"),
                                   "__init__.aout", expect_exit=0)
    check("relalias=100@" in text,
          f"the aliased relative call missed: {text!r}")


# ── (3) arguments, defaults and arity across the boundary ───────────────────

DEFAULT_PROG = """\
from deflib import need_two, need_one

def main(k):
    printf("cross-default=%d@", need_two(1))
    printf("cross-explicit=%d@", need_two(1, 77))
    printf("cross-one=%d@@", need_one(5))
    return 0
"""


def test_a_default_argument_crosses_the_boundary(tmpdir, _):
    """`need_two(1) == 511`, where the callee's own default says 511.

    This is bug (3) and it is the worst class this backend has: nothing was
    refused and nothing was printed, and the value was whatever the caller last
    left in the omitted argument register — measured at 1867609072, a stack
    address. The identical call in the SAME file returned 511 and passing the
    argument explicitly across the same boundary returned 77, which is what
    makes it a boundary bug and not a default bug.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "defaults")
    os.makedirs(root)
    write_tree(root, {"deflib.mojo": DEF_LIB, "prog.mojo": DEFAULT_PROG})
    text, rc = agrees_with_cpython(tmpdir, "default across the boundary", root,
                                   "prog.aout", expect_exit=0)
    check("cross-default=511@" in text,
          f"the default did not arrive: {text!r}")


KEYWORD_PROG = """\
from deflib import need_two, need_one, no_args


def main(k):
    printf("kw-inorder=%d@", need_two(a=1, b=77))
    printf("kw-reordered=%d@", need_two(b=77, a=1))
    printf("kw-default=%d@", need_two(a=1))
    printf("kw-mixed=%d@", need_two(1, b=77))
    printf("kw-one=%d@", need_one(a=5))
    printf("kw-noargs=%d@@", no_args())
    return 0
"""


def test_keyword_arguments_cross_the_boundary(tmpdir, _):
    """A KEYWORD binds a cross-module callee's parameter by NAME.

    The rule is one function on both sides of a dylib boundary and inside one:
    `model.bind_call_arguments` matches each keyword against the callee's own
    `ParamShape`, so the caller may write the arguments in any order, may mix
    them with positionals, and may omit a parameter that has a default. What
    makes this a BOUNDARY case rather than a same-unit one is where the
    declaration comes from: a callee in another image has no `FunctionDef` in
    this unit's registry, so the shape is read off `_extern_decls` — the
    declaration carried by the export manifest, keyed by the SYMBOL the call
    binds. Before that table existed the call's keywords had no parameter list to
    match, and four rows of the sweep's host-import ranking recorded the
    consequence as a compiler limitation.

    It was not one, and the measurement that says so is what this case pins.
    `need_two`'s default is 511 and `need_one` returns its argument, so a
    keyword that bound the wrong slot, dropped an argument, or filled a
    parameter from a register nobody wrote cannot produce these numbers by
    accident — and the CPython half is the SAME text, so the expected binding is
    computed rather than written down. The claim that was wrong, and the
    measurement that corrected it, are `test_a_host_module_call_takes_keywords`
    and `test_a_keyword_binds_with_the_callees_source_gone` below.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "keywords")
    os.makedirs(root)
    write_tree(root, {"deflib.mojo": DEF_LIB, "prog.mojo": KEYWORD_PROG})
    text, rc = agrees_with_cpython(tmpdir, "keywords across the boundary",
                                   root, "prog.aout", expect_exit=0)
    for want in ("kw-inorder=77@", "kw-reordered=77@", "kw-default=511@",
                 "kw-mixed=77@", "kw-one=5@", "kw-noargs=4242@@"):
        check(want in text, f"{want} missing from {text!r}")


def test_a_keyword_is_refused_by_name_across_the_boundary(tmpdir, _):
    """A keyword that names NO parameter is a `TypeError`, by name.

    The other half, and it is the half that makes the row above a RULE rather
    than an omission: accepting an unknown keyword would mean binding it to
    whichever slot was left over, which is the wrong-number shape this file
    exists to prevent. So the refusal NAMES the keyword rather than reporting an
    arity, and it is asserted on both directions — the image must refuse, and
    CPython must refuse, or the case would be pinning a rule the language does
    not have.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "kwbad")
    os.makedirs(root)
    write_tree(root, {
        "deflib.mojo": DEF_LIB,
        "prog.mojo": "from deflib import need_two\n\n\ndef main(k):\n"
                     "    printf(\"%d@@\", need_two(nope=5))\n"
                     "    return 0\n",
    })
    result, _out = build(root, "prog.aout", expect_ok=False)
    refuses(result, "unexpected keyword argument 'nope'")
    rc, _text = cpython(root, "prog.aout")
    check(rc == 1, f"CPython did not refuse `need_two(nope=5)`: exit {rc}")


def test_a_positional_and_a_keyword_on_one_parameter_are_refused(tmpdir, _):
    """`need_two(1, a=2)` names `a` twice, and both sides must refuse it.

    A keyword binds by NAME, so a name that a positional argument already filled
    is a second value for one slot rather than a second slot — and this is the
    only place in the boundary where the answer is a REFUSAL rather than a
    placement, because there is no honest reading of "argument 0 and keyword `a`
    both go to `a`" that is not one of them being dropped.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "kwdup")
    os.makedirs(root)
    write_tree(root, {
        "deflib.mojo": DEF_LIB,
        "prog.mojo": "from deflib import need_two\n\n\ndef main(k):\n"
                     "    printf(\"%d@@\", need_two(1, a=2))\n"
                     "    return 0\n",
    })
    result, _out = build(root, "prog.aout", expect_ok=False)
    refuses(result, "multiple values for argument 'a'")
    rc, _text = cpython(root, "prog.aout")
    check(rc == 1, f"CPython did not refuse `need_two(1, a=2)`: exit {rc}")


def test_a_host_module_call_takes_keywords(tmpdir, _):
    """`pathlib.match_path(b=…, bn=…, an=…, a=…)` — keywords OUT OF ORDER.

    The claim this pins is one the sweep's host-import ranking rested on until it
    was measured: that "a keyword argument to a host module is REFUSED". It was
    measured false on 2026-10-02, on a program that asked for
    `match(path=…, pattern=…)` — names `pathlib.match`
    does not declare, because its parameters are `p` and `pat`. The refusal was
    the language's own rule, correctly applied to a call that had the names
    wrong; it was not a boundary that drops keywords.

So the case asks the question the other way round: a real host module, from
    `formal/hostmods/`, with its REAL declared parameter names, written in
    reverse order. `an` and `bn` are the END indices the callee documents, which
    is why the two end positions are 4 and not 5 for a four-byte pattern — a
    measurement, and the reason the third call answers 0 and the first two
    answer 1, so the agreement below is agreement about three different answers.
    The oracle is the POSITIONAL spelling of the same three calls in the same
    image rather than CPython, and that is the honest one twice over:
    `pathlib.match_path` is this repository's own primitive (CPython's `pathlib`
    exports no such function, so there is nothing to compare it against), and
    what is under test is that the two SPELLINGS agree, which is a claim about
    argument binding rather than about paths.
    """

    fresh_cas()
    root = os.path.join(tmpdir, "hostkw")
    os.makedirs(root)
    write_tree(root, {"prog.mojo": (
        "from pathlib import match_path\n\n\ndef main() -> int:\n"
        '    printf("pos=%d %d %d@", match_path("x.py", 4, "*.py", 4), '
        'match_path("x.py", 4, "*", 1), match_path("x.py", 4, "*.md", 4))\n'
        '    printf("kw=%d %d %d@@", match_path(bn=4, b="*.py", an=4, '
        'a="x.py"), match_path(bn=1, b="*", an=4, a="x.py"), '
        'match_path(bn=4, b="*.md", an=4, a="x.py"))\n'
        "    return 0\n")})
    result, out = build(root, "prog.aout")
    rc, text = run(out)
    check(rc == 0, f"exit {rc}: {text!r}")
    left, _, right = text.partition("@")
    left = left.removeprefix("pos=")
    right = right.removeprefix("kw=").removesuffix("@@")
    check(left == right,
          f"the keyword spelling disagreed with the positional one:\n"
          f"  positional {left!r}\n  keyword    {right!r}")
    check(left == "1 1 0",
          f"the three calls all answered the same thing ({left!r}), so an "
          f"agreement between the two spellings would be agreement about "
          f"nothing")


def test_a_keyword_binds_through_the_manifest_when_the_source_is_gone(tmpdir,
                                                                     _):
    """The declaration is not needed for a NAME: the manifest carries one.

    This is the narrowest limit the keyword row has, and it is not a limit at
    all — which is worth pinning because the obvious way to bound the capability
    is "it needs the callee's source", and that is false. `export_call_contract`
    publishes each export's parameter NAMES (`"positional": ["a", "b"]`), so a
    library shipped without its sources still binds a keyword by name, still
    rejects a name it does not declare, and still puts the argument in the slot
    the name says rather than in the order the caller wrote them. Measured on a
    dylib whose manifest `source` points at a path that is not there:
    `two(b=2, a=1)` is 12 and `two(nope=2)` is refused by name.

    So the whole of the "a keyword argument to a host module is REFUSED" claim
    the host-import ranking rested on reduces to the language's own rule: the
    keyword must name a parameter the callee DECLARES, and every module of that
    ranking is one whose author chooses the declaration.
    """
    import json
    fresh_cas()
    root = os.path.join(tmpdir, "kwmanifest")
    os.makedirs(root)
    write_tree(root, {"countlib.mojo": COUNT_LIB,
                      "prog.mojo": "from countlib import two\n\n\n"
                                   "def main(k):\n"
                                   '    printf("kw=%d@@", two(b=2, a=1))\n'
                                   "    return 0\n"})
    _r, dylib = build_dylib(root, "countlib.dylib", ["countlib.mojo"])
    with open(dylib + ".manifest.json") as f:
        payload = json.load(f)
    published = [e.get("call", {}).get("positional")
                 for e in payload.get("exports", [])
                 if e.get("name") == "two"]
    check(published == [["a", "b"]],
          f"precondition: the manifest publishes `two`'s parameter names, "
          f"which is the fact this case is about: {published!r}")
    _library_with_no_readable_source(root, dylib)
    result, out = build(root, "prog.aout", extra=["--link-dylib", dylib])
    rc, text = run(out)
    check(rc == 0 and text == "kw=12@@",
          f"the keyword did not bind through the manifest: exit {rc}, "
          f"{text!r} (the build said "
          f"{(result.stderr or result.stdout).strip()[-300:]})")
    write_tree(root, {"prog.mojo": "from countlib import two\n\n\n"
                                   "def main(k):\n"
                                   '    printf("%d@@", two(nope=2))\n'
                                   "    return 0\n"})
    result, _out = build(root, "prog.aout", expect_ok=False,
                         extra=["--link-dylib", dylib])
    refuses(result, "unexpected keyword argument 'nope'")


def test_too_many_arguments_across_the_boundary_is_refused(tmpdir, _):
    """`need_one(5, 6)` is a `TypeError`, and it used to build and drop the word.

    The second half of bug (3) and the one that matters as much as the first: an
    argument count that disagrees with the callee's declared arity is a program
    the language rejects, and accepting it means the boundary silently disagrees
    with the contract it exists to carry.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "toomany")
    os.makedirs(root)
    write_tree(root, {
        "deflib.mojo": DEF_LIB,
        "prog.mojo": "from deflib import need_one\n\n\n"
                     "def main(k):\n    printf(\"%d@@\", need_one(5, 6))\n"
                     "    return 0\n",
    })
    result, _out = build(root, "prog.aout", expect_ok=False)
    refuses(result, "too many positional arguments (2 for 1 parameter(s)")
    rc, _text = cpython(root, "prog.aout")
    check(rc == 1,
          f"CPython did not refuse `need_one(5, 6)`: exit {rc}. If CPython "
          f"accepts it this case is asserting a rule the language does not "
          f"have.")


def test_too_few_arguments_across_the_boundary_is_refused(tmpdir, _):
    """`need_two()` is a `TypeError`: `a` has no default to supply it."""
    fresh_cas()
    root = os.path.join(tmpdir, "toofew")
    os.makedirs(root)
    write_tree(root, {
        "deflib.mojo": DEF_LIB,
        "prog.mojo": "from deflib import need_two\n\n\n"
                     "def main(k):\n    printf(\"%d@@\", need_two())\n"
                     "    return 0\n",
    })
    result, _out = build(root, "prog.aout", expect_ok=False)
    refuses(result, "missing required argument 'a'")
    rc, _text = cpython(root, "prog.aout")
    check(rc == 1, f"CPython did not refuse `need_two()`: exit {rc}")


# A PACKAGE that is nothing but a re-export. `leaf` is a real module with real
# functions; `pkg/__init__` publishes them without defining any, which is why
# the package's own manifest carries an EMPTY export table (`forwarded` in
# `model.dylib_export_tables`).
PKG_LEAF = """\
def leaf_two(a, b):
    return a * 10 + b


def leaf_one(a, b=511):
    return a + b
"""

PKG_INIT = """\
from leaf import leaf_one, leaf_two
"""

# `import pkg` and a DOTTED call, where `from leaf import leaf_two` is the same
# function reached by a different spelling. Both spellings have to obey the same
# contract, and the number below is `leaf_two(1) * 10 + 5` so a `b` read out of
# the wrong register cannot produce it.
PKG_DOTTED_PROG = """\
import pkg

def main(k):
    printf("two=%d@", pkg.leaf_two(1, 2))
    printf("one=%d@", pkg.leaf_one(1))
    printf("two-args=%d@@", pkg.leaf_one(1, 2))
    return 0
"""


def test_a_re_exported_callee_obeys_the_same_contract_dotted(tmpdir, _):
    """The control for the two cases below: the dotted spelling still WORKS.

    A package that only re-exports publishes its names through the forwarding
    table rather than its own export table, so a reader that resolved a callee
    without it found no entry for `pkg.leaf_two` at all. That is invisible
    while every call is well formed — the call binds the same symbol either way
    — and it is exactly what makes the two refusals below reachable, so it has
    to be pinned in the direction that says nothing regressed.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "pkg_dotted_ok")
    os.makedirs(root)
    write_tree(root, {"leaf.mojo": PKG_LEAF, "pkg/__init__.mojo": PKG_INIT,
                      "prog.mojo": PKG_DOTTED_PROG})
    text, rc = agrees_with_cpython(tmpdir, "dotted re-export", root,
                                   "prog.aout", expect_exit=0)
    check(text == "two=12@one=512@two-args=3@@",
          f"the dotted re-export did not agree with its own declaration: "
          f"{text!r}")


def test_too_many_arguments_to_a_re_exported_callee_is_refused(tmpdir, _):
    """`pkg.leaf_two(1, 2, 3)` is a `TypeError`, and it used to be dropped.

    The same defect `test_too_many_arguments_across_the_boundary_is_refused`
    pins for `from m import f`, reached by `import m` + `m.f`. The callee was
    resolved through `by_name`/`by_module` only, the package publishes nothing in
    either, so no declaration was found and the third argument was dropped
    without a word: the image built, ran and printed 12 — the answer to
    `leaf_two(1, 2)` for a call that named three arguments.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "pkg_toomany")
    os.makedirs(root)
    write_tree(root, {
        "leaf.mojo": PKG_LEAF,
        "pkg/__init__.mojo": PKG_INIT,
        "prog.mojo": "import pkg\n\n\n"
                     "def main(k):\n    printf(\"%d@@\", pkg.leaf_two(1, 2, 3))\n"
                     "    return 0\n",
    })
    result, _out = build(root, "prog.aout", expect_ok=False)
    refuses(result, "too many positional arguments (3 for 2 parameter(s)")
    rc, _text = cpython(root, "prog.aout")
    check(rc == 1,
          f"CPython did not refuse `pkg.leaf_two(1, 2, 3)`: exit {rc}")


def test_too_few_arguments_to_a_re_exported_callee_is_refused(tmpdir, _):
    """`pkg.leaf_two(1)` is the one that reads uninitialized memory.

    The worse half, and it is why the two spellings have to agree: the omitted
    second parameter landed in whatever the caller last left in that register,
    and the two architectures disagreed about what that was — measured, 80905394
    on arm64 and a different number on x86-64, both printed as ordinary
    decimals with nothing in the build to explain them.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "pkg_toofew")
    os.makedirs(root)
    write_tree(root, {
        "leaf.mojo": PKG_LEAF,
        "pkg/__init__.mojo": PKG_INIT,
        "prog.mojo": "import pkg\n\n\n"
                     "def main(k):\n    printf(\"%d@@\", pkg.leaf_two(1))\n"
                     "    return 0\n",
    })
    result, _out = build(root, "prog.aout", expect_ok=False)
    refuses(result, "missing required argument 'b'")
    rc, _text = cpython(root, "prog.aout")
    check(rc == 1, f"CPython did not refuse `pkg.leaf_two(1)`: exit {rc}")


VAR_LIB = """\
def with_defaults(a, b=7, c=9):
    return a * 100 + b * 10 + c


def variadic(head, *rest):
    return head * 2
"""

VAR_PROG = """\
from varlib import with_defaults, variadic

def main(k):
    printf("one=%d@", with_defaults(1))
    printf("two=%d@", with_defaults(1, 2))
    printf("three=%d@", with_defaults(1, 2, 3))
    printf("var=%d@@", variadic(4, 5, 6))
    return 0
"""


def test_every_argument_count_and_a_variadic_agree_with_cpython(tmpdir, _):
    """Defaults at both ends of the list, and `*rest`, across the boundary.

    `*rest` is here because the boundary used to pass arguments positionally
    with no arity question at all, so this is the case where a decision to
    "materialize the defaults" could have gone on to invent register space for
    a variadic. It does not: `bind_call_arguments` drops what follows the
    variadic's position, and `check_module_symbols` refuses a body that reads
    its variadic parameter, so the drop cannot be a silent loss.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "variadic")
    os.makedirs(root)
    write_tree(root, {"varlib.mojo": VAR_LIB, "prog.mojo": VAR_PROG})
    agrees_with_cpython(tmpdir, "defaults at every count + variadic", root,
                        "prog.aout", expect_exit=0)


def test_a_local_default_and_a_cross_module_default_agree(tmpdir, _):
    """The two answers side by side, in one program.

    The control for `test_a_default_argument_crosses_the_boundary`, and the
    reason that case is a boundary bug rather than a default bug: the identical
    `local_two(1)` — same default, same image, same register — has to return
    511 whether or not a module is involved.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "local_vs_cross")
    os.makedirs(root)
    write_tree(root, {
        "deflib.mojo": DEF_LIB,
        "prog.mojo": "from deflib import need_two\n\n\n"
                     "def local_two(a, b=511):\n    return b\n\n\n"
                     "def main(k):\n"
                     "    printf(\"cross=%d@\", need_two(1))\n"
                     "    printf(\"local=%d@@\", local_two(1))\n"
                     "    return 0\n",
    })
    text, rc = agrees_with_cpython(tmpdir, "local vs cross-module default",
                                   root, "prog.aout", expect_exit=0)
    check("cross=511@local=511@@" in text,
          f"the two defaults disagree: {text!r}")


# ── (4) a struct from a `--link-dylib` library ─────────────────────────────

HEAP_LIB = """\
struct Bag:
    var n: Int
    var tag: Int

    def __init__(out self):
        self.n = 0
        self.tag = 0

    def __len__(self) -> Int:
        return self.tag

    def add(self, a: Int) -> Int:
        self.n = self.n + a
        return self.n


struct Wide:
    var a: Int
    var b: Int

    def __init__(out self):
        self.a = 0
        self.b = 0

    def sum(self) -> Int:
        return self.a + self.b
"""

# NO import statement: `--link-dylib` is the only way `Bag` reaches this file,
# which is the shape the boundary exists for and the one that was refused.
LINK_PROG = """\
def main(k):
    var b = Bag()
    b.n = 4
    b.tag = 7
    printf("n=%d@", b.n)
    printf("tag=%d@", b.tag)
    printf("len=%d@", len(b))
    printf("add=%d@", b.add(3))
    var w = Wide()
    w.a = 11
    w.b = 22
    printf("wsum=%d@@", w.sum())
    return 0
"""


def test_a_linked_dylibs_struct_is_usable_with_no_import(tmpdir, _):
    """Fields, `len()`, and methods on a struct that came from a dylib.

    Bug (4). The library advertised the struct's METHODS in its manifest and not
    its DECLARATION, so `b.n = 4` was refused with a repair that cannot be
    followed — "bind the base from a constructor THIS MODULE declares", for a
    struct declared in a file this build does not have.

    `w.a = 11` is spelled out rather than left to `Wide()`'s constructor
    deliberately: bug (5) below says a `S()` whose `__init__` takes no required
    parameter does NOT run the body, and pinning that here as well would make
    this case fail for two reasons at once.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "linkdylib")
    os.makedirs(root)
    write_tree(root, {"heaplib.mojo": HEAP_LIB, "prog.mojo": LINK_PROG})
    _r, dylib = build_dylib(root, "heaplib.dylib", ["heaplib.mojo"])
    # `preamble` is the ONLY thing the CPython side gets that the image does
    # not, and it is the module's own import: the program deliberately has none,
    # because `--link-dylib` is the only way `Bag` reaches it and that is the
    # shape under test. CPython has no such boundary, so the names have to come
    # from somewhere.
    text, rc = agrees_with_cpython(
        tmpdir, "struct from a linked dylib", root, "prog.aout",
        extra=["--link-dylib", dylib],
        preamble="from heaplib import Bag, Wide\n\n")
    check(rc == 0, f"the linked-struct program exited {rc}, CPython 0")
    check(text == "n=4@tag=7@len=7@add=7@wsum=33@@",
          f"the linked struct did not behave like its own declaration: "
          f"{text!r}")


def test_a_linked_dylib_whose_source_is_gone_is_still_refused(tmpdir, _):
    """The honest direction: no declaration to read is a refusal, not a guess.

    The control for the case above. When the library's recorded source is not
    readable this image has no field list, no frame layout and no way to know
    `len(b)` means `b.__len__()`, so the program is refused — which is the
    correct verdict, since emitting a `BL` against a symbol nothing defines, or
    guessing a layout, is the outcome the whole mechanism exists to prevent.

    **And the refusal has to be the one that NAMES the library**, because that
    is the only message a reader can act on: `var b = Bag()` is a construction
    of a struct that arrived in a manifest and not in a declaration, and the two
    messages this used to be are both about something else. `b.n` was refused by
    `field_access_refusal`, which is raised from an emitter's slot-allocator
    fall-through and is handed a slot key and nothing else — so it cannot say
    the struct is one hop away, and its repair ("bind the base from a
    constructor whose declaration THIS IMAGE can see") is a true sentence about a
    fact the reader cannot change. With no field access at all the same program
    was refused by the bind audit ("the image would bind 1 symbol(s) that
    nothing provides: Bag"), which says the opposite of the truth: the library
    on the link line exports `Bag`'s methods, and `Bag` is in every one of those
    manifest entries.

    So the refusal is raised in the BUILD PASS, where the construction is, and it
    reports the three things a reader can check — the struct, the library that
    has it, and the path its manifest records for the source this build cannot
    read — with the two repairs that exist (rebuild the library where the source
    is readable, or link the module by IMPORT) and NOT the one that does not
    (re-declare the struct here, which would be a different type with the same
    name and a layout the library's methods were not compiled against).
    """
    import json
    fresh_cas()
    root = os.path.join(tmpdir, "linkdylib_gone")
    os.makedirs(root)
    write_tree(root, {"heaplib.mojo": HEAP_LIB, "prog.mojo": LINK_PROG})
    _r, dylib = build_dylib(root, "heaplib.dylib", ["heaplib.mojo"])
    manifest_path = dylib + ".manifest.json"
    with open(manifest_path) as f:
        payload = json.load(f)
    check(payload.get("source"),
          "precondition: the manifest records the module's source, which is "
          "what this case makes unreadable")
    payload["source"] = os.path.join(root, "not", "there", "heaplib.mojo")
    with open(manifest_path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")
    result, _out = build(root, "prog.aout", expect_ok=False,
                         extra=["--link-dylib", dylib])
    refuses(result, "Bag() constructs a struct this image has no DECLARATION for")
    text = result.stderr or result.stdout
    for gone in ("is bound here as a parameter",
                 "constructor this module declares (`x = S()`)",
                 "symbol(s) that nothing provides"):
        check(gone not in text,
              f"the refusal still says {gone!r}, which is false about a "
              f"library whose source this build cannot read: {text[-400:]}")
    # The method the message quotes is read off the manifest rather than written
    # here, so this cannot pin an export ORDER the manifest does not promise —
    # only the fact that the sentence is quoting the library's own table.
    methods = {e["signature"] for e in payload["exports"]
               if e.get("kind") == "method"}
    check(methods and any(sig in text for sig in methods),
          f"the refusal quotes none of the library's own method exports "
          f"{sorted(methods)}, so its claim that the library has the struct is "
          f"not one it can show: {text[-400:]}")
    for want in ("heaplib.dylib",                 # the library that has it
                 os.path.join("not", "there", "heaplib.mojo"),   # its source
                 "rebuild the library",           # repair 1
                 "from heaplib import Bag",       # repair 2
                 "Do not re-declare the struct here"):
        check(want in text,
              f"the refusal does not offer {want!r}, so the reader is sent "
              f"after a repair that does not exist: {text[-400:]}")


def test_a_gone_source_is_refused_whatever_the_construction_spells(tmpdir, _):
    """The same refusal with no field access and with arguments — two routes.

    The refusal above is reached through `b.n`, and it is worth pinning that the
    ANSWER does not depend on which construct of the program happens to be
    reached first, because there were two other answers before it and neither
    was true:

      * with no field access at all, `var b = Bag()` was a dangling call and the
        bind audit reported it — "the image would bind 1 symbol(s) that nothing
        provides: Bag", which asserts the opposite of the manifest's contents;
      * with ARGUMENTS, `Bag(1, 2)` was no constructor call this path has a
        shape for, and it was refused for that. A check written against an
        EMPTY argument list would have let this one past, which is the mistake
        the bug doc's own last paragraph records: the scan has to be "a name this
        image has no declaration for that a linked library does", not "a name
        that was called with no arguments".

    Both architectures, because a refusal that differs between them is the
    two-backend split this file exists to keep closed, and both are refusals
    before and after — what is asserted is the WORDS.
    """
    import json
    fresh_cas()
    variants = {
        "noargs": "def main(k):\n    var b = Bag()\n    return 0\n",
        "args": "def main(k):\n    var b = Bag(1, 2)\n    return 0\n",
    }
    for label, prog in variants.items():
        for arch in ("arm64", "x86_64"):
            root = os.path.join(tmpdir, f"gone_{label}_{arch}")
            os.makedirs(root)
            write_tree(root, {"heaplib.mojo": HEAP_LIB, "prog.mojo": prog})
            _r, dylib = build_dylib(root, "heaplib.dylib", ["heaplib.mojo"])
            manifest_path = dylib + ".manifest.json"
            with open(manifest_path) as f:
                payload = json.load(f)
            payload["source"] = os.path.join(root, "not", "there",
                                            "heaplib.mojo")
            with open(manifest_path, "w") as f:
                json.dump(payload, f, indent=1, sort_keys=True)
                f.write("\n")
            result, _out = build(root, "prog.aout", expect_ok=False, arch=arch,
                                 extra=["--link-dylib", dylib])
            refuses(result,
                    "Bag() constructs a struct this image has no DECLARATION "
                    "for")
            text = result.stderr or result.stdout
            check("symbol(s) that nothing provides" not in text,
                  f"{label}/{arch}: the bind audit's answer is back, and it "
                  f"says the library provides nothing: {text[-300:]}")


# ── (3b) the same three arity questions with no DECLARATION to read ─────────
#
# The three cases above are answered by `bind_call_arguments`, which reads the
# callee's FunctionDef out of the library's own source. A library shipped
# without its sources has none, and "no declaration" used to mean "no
# contract": the arguments were passed exactly as written and the callee read
# the rest out of whatever this image last left in those registers. The
# manifest publishes the contract (`model.export_call_contract`), so these three
# are refused instead — and the fourth, which is the control, is not.

COUNT_LIB = """\
def two(a, b):
    return a * 10 + b


def with_default(a, b=7, c=9):
    return a * 100 + b * 10 + c


def variadic(head, *rest):
    return head * 2


def no_args():
    return 4242
"""

COUNT_PROG = """\
def main(k):
    printf("two=%d@", two(1, 2))
    printf("three=%d@", with_default(1, 2, 3))
    printf("var=%d@", variadic(4, 5, 6))
    printf("none=%d@@", no_args())
    return 0
"""


def _library_with_no_readable_source(root, dylib):
    """Point the manifest's `source` at a path that is not there.

    The shape a library shipped without its sources produces, and the one the
    doc for the linked-struct case names. It is done by editing the manifest
    rather than by deleting the file because the IMPORTING program has to be
    able to resolve `from heaplib import …` in the first place, and the point
    is precisely that this image cannot read the declaration AFTER it has bound
    the symbol.
    """
    import json
    path = dylib + ".manifest.json"
    with open(path) as f:
        payload = json.load(f)
    check(payload.get("source"),
          "precondition: the manifest records the module's source, which is "
          "what this helper makes unreadable")
    payload["source"] = os.path.join(root, "not", "there", "gone.mojo")
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")


def test_the_manifests_call_contract_holds_when_there_is_no_declaration(tmpdir,
                                                                      _):
    """The control for the three refusals below: every admitted count still runs.

    `variadic(4, 5, 6)` is here because it is the one count a strict reading of
    "the call supplies more arguments than the callee has parameters" would
    refuse, and refusing it would be a NEW refusal of a program that is right:
    the arguments past the fixed ones are `*rest`'s and are dropped by design,
    which is what `bind_call_arguments` does for a callee whose declaration IS
    readable. A caller that cannot read it has to reach the same verdict.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "count_ok")
    os.makedirs(root)
    write_tree(root, {"countlib.mojo": COUNT_LIB, "prog.mojo": COUNT_PROG})
    _r, dylib = build_dylib(root, "countlib.dylib", ["countlib.mojo"])
    _library_with_no_readable_source(root, dylib)
    result, out = build(root, "prog.aout", extra=["--link-dylib", dylib])
    rc, text = run(out)
    check(rc == 0 and text == "two=12@three=123@var=8@none=4242@@",
          f"an admitted count stopped working with no declaration: exit {rc}, "
          f"{text!r} (the build said "
          f"{(result.stderr or result.stdout).strip()[-300:]})")


def test_too_many_arguments_with_no_declaration_is_refused(tmpdir, _):
    """`two(1, 2, 3)` with the library's source gone: the manifest knows.

    The same wrong answer as `test_too_many_arguments_across_the_boundary_is_
    refused` — the third argument dropped and the answer to `two(1, 2)`
    returned — reached through the one path `bind_call_arguments` cannot cover.
    Before the manifest published a call contract, an `arity` field was already
    there and unused; this is the reader for it.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "count_toomany")
    os.makedirs(root)
    write_tree(root, {
        "countlib.mojo": COUNT_LIB,
        "prog.mojo": "def main(k):\n    printf(\"%d@@\", two(1, 2, 3))\n"
                     "    return 0\n",
    })
    _r, dylib = build_dylib(root, "countlib.dylib", ["countlib.mojo"])
    _library_with_no_readable_source(root, dylib)
    result, _out = build(root, "prog.aout", expect_ok=False,
                         extra=["--link-dylib", dylib])
    refuses(result, "too many positional arguments (3 for 2 parameter(s)")
    check("countlib published" in (result.stderr or result.stdout),
          "the refusal does not say which module published the count")


def test_too_few_arguments_with_no_declaration_is_refused(tmpdir, _):
    """`two(1)` with the library's source gone: the register is never written.

    Measured before this: 1798665114 on arm64 and a different number on x86-64,
    both printed as ordinary decimals with nothing in the build to explain them,
    where CPython refuses the call.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "count_toofew")
    os.makedirs(root)
    write_tree(root, {
        "countlib.mojo": COUNT_LIB,
        "prog.mojo": "def main(k):\n    printf(\"%d@@\", two(1))\n"
                     "    return 0\n",
    })
    _r, dylib = build_dylib(root, "countlib.dylib", ["countlib.mojo"])
    _library_with_no_readable_source(root, dylib)
    result, _out = build(root, "prog.aout", expect_ok=False,
                         extra=["--link-dylib", dylib])
    refuses(result, "missing required argument(s) 'b'")


def test_a_default_this_image_cannot_materialize_is_refused(tmpdir, _):
    """`with_default(1)`: a legal count, and still not something to emit.

    The count is right — one argument, one required parameter — so no arity
    check can object to it. But `b=7` and `c=9` are EXPRESSIONS in the callee's
    declaration, and this image cannot read them, so it cannot write them into
    the registers the callee will read: measured, `with_default(1)` returning
    357586946 where the callee's own defaults say 179. The manifest says which
    parameters have defaults, which is enough to know that the gap is one this
    image cannot fill, and that is what the refusal is for.

    The control for this is `test_a_default_argument_crosses_the_boundary`:
    with the source readable, the same call returns 511 and nothing is refused.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "count_default")
    os.makedirs(root)
    write_tree(root, {
        "countlib.mojo": COUNT_LIB,
        "prog.mojo": "def main(k):\n    printf(\"%d@@\", with_default(1))\n"
                     "    return 0\n",
    })
    _r, dylib = build_dylib(root, "countlib.dylib", ["countlib.mojo"])
    _library_with_no_readable_source(root, dylib)
    result, _out = build(root, "prog.aout", expect_ok=False,
                         extra=["--link-dylib", dylib])
    refuses(result, "'b', 'c' have a default that only the callee's DECLARATION")


# ── (5) `S()` — the control, with no module involved ────────────────────────

ZERO_INIT_PROG = """\
struct Z:
    var a: Int
    var b: Int

    def __init__(out self, a: Int = 8, b: Int = 9):
        self.a = a
        self.b = b


struct NoCtor:
    var a: Int
    var b: Int


struct NeedsArgs:
    var n: Int
    var m: Int

    def __init__(out self, n: Int, m: Int):
        self.n = n
        self.m = m


def main(k):
    var z = Z()
    printf("z=%d@", z.a * 100 + z.b)
    var p = NoCtor()
    printf("p=%d@", p.a * 100 + p.b)
    var q = NeedsArgs(3, 4)
    printf("q=%d@@", q.n * 10 + q.m)
    return 0
"""


def test_a_zero_argument_construction_runs_a_zero_required_constructor(tmpdir, _):
    """`Z()` is `a == 8, b == 9`, and `NoCtor()` is two zeros.

    Bug (5), and the CONTROL for (3): the same disagreement with the language,
    reached with no module anywhere. Both halves are in one program because the
    two answers are the difference between "a zero-argument construction runs a
    constructor" and "every construction runs one", and only the pair says which.

    `NeedsArgs(3, 4)` is the third shape and the one that used to be wrong in
    the other direction: a call WITH arguments to a constructor that requires
    them, which is the case the inline was built for and the only one that
    worked before.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "zeroinit")
    os.makedirs(root)
    write_tree(root, {"prog.mojo": ZERO_INIT_PROG})
    text, rc = agrees_with_cpython(tmpdir, "zero-argument construction", root,
                                   "prog.aout", expect_exit=0)
    check(text == "z=809@p=0@q=34@@",
          f"the zero-argument construction did not run its constructor: "
          f"{text!r}")
    check("z=809@" in text,
          f"`Z()` did not carry the constructor's own defaults (8 and 9): "
          f"{text!r}")


def test_a_zero_argument_construction_of_a_constructor_that_needs_arguments(
        tmpdir, _):
    """`Bag4()` against `def __init__(out self, n, m)` is a `TypeError`.

    The other half of bug (5): it used to build, run and report two zeros, so a
    caller that meant `Bag4(0, 0)` got it by accident and a caller that meant
    anything else got a value nobody wrote.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "zeroneeds")
    os.makedirs(root)
    write_tree(root, {"prog.mojo":
                      "struct Bag4:\n"
                      "    var n: Int\n"
                      "    var m: Int\n"
                      "\n"
                      "    def __init__(out self, n: Int, m: Int):\n"
                      "        self.n = n\n"
                      "        self.m = m\n"
                      "\n"
                      "\n"
                      "def main(k):\n"
                      "    var b = Bag4()\n"
                      "    return b.get()\n"})
    result, _out = build(root, "prog.aout", expect_ok=False)
    refuses(result, "none of them takes that count")


# ── (6) a frame address handed across the boundary ──────────────────────────
#
# The other kind of thing that crosses: not an ARGUMENT but a frame ADDRESS,
# and whether it can mean what the caller thinks depends on a contract the
# DEFINING module has to publish (`formal/build.py`'s `_frame_param_contract`,
# read by `formal/model.py`'s `resolve_frame_parameter_contract`).  The positive
# and negative cases of the construct live in `test_formal_run.py`'s
# `CROSS_MODULE_CASES` as built-and-run programs; what is HERE is the thing those
# cannot see, which is the CONTRACT ITSELF — the published table, and the layer
# a refusal names when the table says nothing.
#
# These pin a defect that was measured, fixed, and whose filing is deleted: a
# function holding no frame published NO contract at all rather than a contract
# of `Nones`, so `[]` was `_export_frame_contract`'s "this compilation could not
# classify it" and `resolve_frame_parameter_contract` read `position 0 >=
# len([])` as "not-exported" — a refusal naming a missing EXPORT about a
# function the manifest lists with an arity. The filing was
# `FORMAL_cross_image_frame_contract_is_not_published_for_a_free_function`,
# and it is deleted: fixed, with these cases as the proof.
#
# The module is one framed struct plus a function that holds nothing, which is
# the ordinary shape of a module with a data class and some helpers, and the
# middle case between the two that were already right: a module with no framed
# struct at all publishes `[None] * n` for everything, and a function the fixpoint
# classified publishes its real entries.
CONTRACT_LIB = """\
struct P:
    var a: Int
    var b: Int


def plain(x: Int, by: Int) -> Int:
    return x + by


def takes_frame(p: P) -> Int:
    return p.a * 10 + p.b
"""

CONTRACT_PROG = """\
from conlib import P, plain

def main(k):
    var p = P()
    p.a = 3
    p.b = 4
    return plain(p, k)
"""


def _contract_for(dylib, name):
    """`{export name: frame_params}` out of a dylib's own manifest."""
    import json
    with open(dylib + ".manifest.json") as f:
        payload = json.load(f)
    return {e["name"]: e.get("frame_params") for e in payload.get("exports")}


def test_every_exported_function_publishes_a_per_parameter_contract(tmpdir, _):
    """Both functions in `CONTRACT_LIB` publish one entry per parameter.

    The publication itself rather than the hand-off it enables, because
    `test_formal_run.py` measures the hand-off and would report the same red for
    a dozen different reasons: it cannot say WHICH half was wrong.  Two entries
    in this table and the hand-off cases settle which.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "contract")
    os.makedirs(root)
    write_tree(root, {"conlib.mojo": CONTRACT_LIB})
    _r, dylib = build_dylib(root, "conlib.dylib", ["conlib.mojo"])
    table = _contract_for(dylib, "conlib")
    check("plain" in table and "takes_frame" in table,
          f"precondition: both functions are exported, got {sorted(table)}")
    check(table["plain"] == [None, None],
          f"a function holding no frame must publish one `None` per parameter, "
          f"not {table['plain']!r} — `[]` is read as 'could not classify it' "
          f"and a missing entry as 'not an export'")
    check(table["takes_frame"] == [["P"]],
          f"a parameter declared `p: P` is a holder of P by construction: "
          f"{table['takes_frame']!r}")


def test_a_frame_address_reaching_an_ordinary_word_names_the_contract(tmpdir, _):
    """`plain(p, k)` is refused as a PLAIN PARAMETER, not as a missing export.

    The diagnostic half of the case above, and it is why the table is worth
    pinning. Both sentences refuse the program, and only one of them is TRUE
    about it: `plain` is on the manifest with an arity of 2, so "the manifest
    does not list it as an export" sends the reader to check an export that is
    there, while what actually happened is that the callee's own compilation
    published `plain`'s parameter 0 as a word.

    The refusal's WORDS are the assertion — the verdict (refused) is identical
    under both mistakes, and a diagnostic that points at the wrong layer is the
    failure mode this backend's messages are otherwise written against.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "contract_plain")
    os.makedirs(root)
    write_tree(root, {"conlib.mojo": CONTRACT_LIB, "prog.mojo": CONTRACT_PROG})
    result, _out = build(root, "prog.aout", expect_ok=False)
    text = result.stderr or result.stdout
    refuses(result, "is an ordinary word, NOT a frame holder")
    check("does not list it as an export" not in text,
          f"the refusal blamed a missing EXPORT for a function the manifest "
          f"lists with an arity of 2:\n{text.strip()[-500:]}")


# ── one measurement, not two: the executor's own copy ───────────────────────

def test_the_executors_answer_the_same_questions(tmpdir, _):
    """arm64 and x86-64 must return the same VERDICT, construct by construct.

    Not a value comparison — a verdict comparison: build the same program for
    both architectures and require the same answer, "built and exited 0"
    against "refused". Every construct above is architecture-free (the call
    spelling, the argument binding, the frame layout, the overload selection),
    so a construct that lowers on one and is refused on the other is the
    two-architecture split this backend has had before: the same source, two
    answers, and a suite that was green throughout because only one
    architecture was exercised.
    """
    cases = [
        ("alias", {"deflib.mojo": DEF_LIB, "prog.mojo": ALIAS_PROG}),
        ("defaults", {"deflib.mojo": DEF_LIB, "prog.mojo": DEFAULT_PROG}),
        ("keywords", {"deflib.mojo": DEF_LIB, "prog.mojo": KEYWORD_PROG}),
        ("variadic", {"varlib.mojo": VAR_LIB, "prog.mojo": VAR_PROG}),
        ("zeroinit", {"prog.mojo": ZERO_INIT_PROG}),
        ("local_vs_cross", {"deflib.mojo": DEF_LIB, "prog.mojo":
                            "from deflib import need_two\n\n\n"
                            "def local_two(a, b=511):\n    return b\n\n\n"
                            "def main(k):\n"
                            '    printf("cross=%d@", need_two(1))\n'
                            '    printf("local=%d@@", local_two(1))\n'
                            "    return 0\n"}),
    ]
    for name, files in cases:
        verdicts = {}
        for arch in ("arm64", "x86_64"):
            root = os.path.join(tmpdir, f"arch_{name}_{arch}")
            os.makedirs(root)
            write_tree(root, files)
            result, out = build(root, "prog.aout", expect_ok=False,
                                arch=arch)
            verdicts[arch] = ("refused" if result.returncode != 0
                              else f"exit {run(out)[0]}")
        check(verdicts["arm64"] == verdicts["x86_64"],
              f"{name}: arm64 {verdicts['arm64']} but x86-64 "
              f"{verdicts['x86_64']}")
        check(verdicts["arm64"] == "exit 0",
              f"{name}: neither architecture ran it ({verdicts['arm64']})")


# ── (6) a module-level STORE the image already holds, across the boundary ────
#
# The other half of what a dylib boundary carries is not an argument but the
# MODULE'S OWN DATA. `model.module_body` already answers "does this top-level
# statement HAVE TO RUN?" with two exemptions — a value that FOLDS (`X = 5`,
# substituted at each read) and a name that is a `__DATA` SLOT whose initializer
# the image lays out before anything runs (`X = ["a", "b"]`, which is
# storage-shaped rather than foldable). So a module whose top level is only those
# is not "an API that is its top-level statements", and it is importable.
#
# This case exists because 16 files in the 668-file sweep
# (`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md` §3) are refused for the OTHER
# answer — `module_loader.py`, `tools/memslot.py`, `formal/x86_64.py`,
# `determinism_trace.py` have a body that genuinely must run — and the fix for
# those is a load-time initializer in both object writers. **That fix cannot be
# attempted without knowing that what is already in the image arrives intact**, and
# nothing asserted that: a dylib `__DATA` slot carrying `5` where the source says
# `5` would read as `0` and this suite would be green, because every other case in
# this file crosses the boundary with a VALUE and never with the module's own
# initialized data. So this is the test the fix's precondition needs, written
# before the fix.
#
# The module is named `globlib` rather than something shorter because the CPython
# oracle puts this directory on `PYTHONPATH` and a module named after a stdlib
# module would shadow it.
GLOBLIB = """\
COUNT = 5
NAMES = ["alpha", "beta"]


def get() -> Int:
    return COUNT


def bump():
    global COUNT
    COUNT = COUNT + 1


def width() -> Int:
    return len(NAMES)
"""

GLOBAL_PROG = """\
def main(k):
    printf("first=%d@", get())
    bump()
    bump()
    printf("second=%d@", get())
    printf("width=%d@@", width())
    return 0
"""


def test_a_module_stores_that_the_image_already_holds_cross_the_boundary(
        tmpdir, _):
    """`COUNT = 5` read through another module is 5, and stays 7 after two writes.

    Three things in one case, and each is a way the boundary could be wrong
    without anything looking broken:

      * the FOLDED store (`COUNT = 5`, nothing writes it at first) has to arrive
        as the value the source says and not as the zero an unwritten slot gives;
      * the SLOT store (`NAMES = ["alpha", "beta"]`, which is storage-shaped, so
        it is a `__DATA` word holding a blob address) has to arrive with its blob
        laid out — `width()` is `len()` of it across the boundary;
      * the WRITE (`bump()` does `global COUNT; COUNT = COUNT + 1`) has to reach
        the module's own storage and not a register in the caller, so the second
        read is 7 and not 5.

    Compared with CPython on the same text, like every other case here: a value
    written down beside this test would be a second answer to the same question.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "globinit")
    os.makedirs(root)
    write_tree(root, {"globlib.mojo": GLOBLIB, "prog.mojo": GLOBAL_PROG})
    _r, dylib = build_dylib(root, "globlib.dylib", ["globlib.mojo"])
    text, rc = agrees_with_cpython(
        tmpdir, "module stores across the boundary", root, "prog.aout",
        expect_exit=0, extra=["--link-dylib", dylib],
        preamble="from globlib import get, bump, width\n")
    check(text == "first=5@second=7@width=2@@",
          f"the module's own initialized data did not survive the boundary: "
          f"{text!r}")


# The module whose body must RUN, and the program that proves it did.
#
# `COMPUTED = compute()` is not foldable and not a slot initializer — the value
# does not exist until something calls `compute()` — so it is a statement with an
# effect, and an effect nothing performs is the silent no-op this boundary exists
# to prevent. It used to be REFUSED ("this module's API is its top-level
# statements … a library has no entry point to run them"), which was honest about
# the container and cost 16 files of this repository; the entry point was what was
# missing, and both object writers now emit one.
#
# `print` and not `printf`, and that is so the CPython oracle still applies:
# every other case in this file compares with CPython, and `printf` is the one
# thing the module side of the comparison cannot use — this file's own note says
# the modules "get no shim, because they are imported for their declarations and
# print nothing". This is the first module here that PRINTS, and `print` is what
# keeps the oracle an oracle instead of a second copy of the expectation.
# `compute` is DEFINED BEFORE the store that calls it, and that is the oracle's
# requirement rather than the source's: this backend hoists a `def`, so the two
# orders compile alike, but CPython runs the statements top to bottom and a call
# to a function defined lower down is a `NameError` — which would have made the
# CPython side print half its output and die, and the case would then be asserting
# against a half-answer.
BODY_LIB = """\
print("body")
LITERAL = 3


def compute() -> Int:
    return 7


COMPUTED = compute()


def get() -> Int:
    return LITERAL
"""

# The program declares a `main` because this file's CPython harness ends with
# `sys.exit(main(0))` — every case here is shaped so both sides run `main`, and
# the formal side's startup stub calls it too.
BODY_PROG = """\
from computed import get


def main(k):
    print("main", get())
    return 0
"""


def test_a_module_body_runs_at_load_across_the_boundary(tmpdir, _):
    """A library's module body runs WHEN THE LIBRARY LOADS, before `main`.

    This is the CONTROL that replaced "a body with code in it is refused", and
    it is the same claim as the case above read from the other side: that one
    pins the stores the IMAGE holds, this one pins the statement the image has
    to RUN. Both are needed because they are two different ways a module's own
    top level can fail to arrive — a wrong word in `__DATA`, and a body that
    never executed — and only the first was covered before.

    The body's effect is a `print` because that is the one thing a library can do
    that is observable from the PROGRAM's stdout and from nowhere else; and it
    comes FIRST because the position is the claim: a load-time initializer runs
    after the library's dependencies are mapped and before `main`, which is where
    CPython puts a module body's statements at import. So `body` then `main 3`
    is the whole answer, and it is compared with CPython on the same text so the
    two lines are two independent readings rather than one written down twice.

    The program reaches the library through its `import`, not through
    `--link-dylib`: two copies of one module on one link line would run the body
    twice, and a case about "the body ran once, at load" must not be the thing
    that puts the module on the line twice.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "globbody")
    os.makedirs(root)
    write_tree(root, {"computed.mojo": BODY_LIB, "prog.mojo": BODY_PROG})
    text, rc = agrees_with_cpython(
        tmpdir, "module body at load time", root, "prog.aout", expect_exit=0)
    check(text == "body\nmain 3\n",
          f"the module body's statements did not run at load time, or ran in "
          f"the wrong order against main: {text!r}")


# ── (6) a CONTAINER-returning export whose body calls helpers on the buffer ──
#
# The export's declared return type is a container, its body calls a private
# helper, and the helper's parameter is UNTYPED and receives the scratch buffer
# the export then reads. That shape was bisected to here, and its symptom is the
# reason this file is the right home for it rather than a refusal row: the image
# STARTED, printed nothing at all — not even the first `printf` in `main` — and
# exited 1. The callee's helper trapped in its FIRST statement, the trap is a
# raw `exit(1)` syscall, and a raw exit does not flush stdio, so every buffered
# line the caller had printed went with it. "The caller's frame is laid out
# around this callee" was the wrong reading of an artefact of buffering.
#
# `mod.mojo` is the minimum that reproduces it: one `malloc`'d scratch buffer, one
# private helper that stores through an untyped parameter, one count store, one
# read-back of what the helper wrote. Before the callee's parameter took the
# convention its call site uses, the store landed at `segs + 16` with the count
# word at `segs + 0` still zero, so the container walk's bounds check fired and
# the raw exit took the process with it — measured on this tree: exit 1 and zero
# bytes of output.
#
# There is no CPython oracle here and that is stated rather than worked around:
# the program is about the REPRESENTATION of a returned blob — word 0 is the
# count, element i is at `base + 8 + 8i` — and CPython's `List` is a different
# representation of the same list, so `agrees_with_cpython` would be comparing
# two languages rather than two compilations. What the numbers ARE is derived
# from the source in front of the reader: `_split` returns 1, `b[0] = ns` makes
# the count 1, `b[1] = segs[1]` copies the helper's 43 into element 0, so
# `len(paths)` is 1 and `paths[0]` is 43. `test_formal_run.py`'s
# `both_arch_an_untyped_parameter_indexes_the_same_pointer_as_an_annotated_one`
# is the one-image half of the same claim.
CONTAINER_LIB = """\
def _split(pattern, segs) -> int:
    segs[1] = 43
    return 1


def collect(pattern) -> List[Int]:
    var segs: Pointer[Int64] = malloc(8 * 4)
    memset(segs, 0, 32)
    var ns = _split(pattern, segs)
    var b: Pointer[Int64] = malloc(8 * (ns + 2))
    memset(b, 0, 8 * (ns + 2))
    b[0] = ns
    b[1] = segs[1]
    free(segs)
    return b
"""

CONTAINER_PROG = """\
from mod import collect


def main(k):
    printf("start\\n")
    var paths = collect("*.py")
    printf("n=%d e0=%d", len(paths), paths[0])
    return 0
"""


def test_a_container_returning_export_whose_helpers_take_the_buffer(tmpdir, _):
    """`collect` returns `List[Int]` and `_split` fills the buffer it is given.

    Asserts the OUTPUT and not merely the exit status, because the exit status
    is what the bug reported: a program that printed nothing and exited 1 is
    indistinguishable from a program that printed nothing and exited 1 for a
    different reason. `start` is in the expected text for the same reason — it
    is the line the buffering artefact swallowed, so its presence is the
    assertion that the callee's first statement ran at all.
    """
    fresh_cas()
    root = os.path.join(tmpdir, "container_export")
    os.makedirs(root)
    write_tree(root, {"mod.mojo": CONTAINER_LIB, "prog.mojo": CONTAINER_PROG})
    result, out = build(root, "prog.aout")
    rc, text = run(out)
    check(rc == 0,
          f"the image exited {rc}, not 0 — and with no output at all that is "
          f"the shape this case is about, since a raw exit(1) syscall does not "
          f"flush stdio: {text!r}")
    check(text == "start\nn=1 e0=43",
          f"the helper's store and the export's read-back of it disagree: "
          f"{text!r}")


TESTS = [
    ("a module's own folded and slot stores cross the boundary",
     test_a_module_stores_that_the_image_already_holds_cross_the_boundary),
    ("a module body runs at load time, before main",
     test_a_module_body_runs_at_load_across_the_boundary),
    ("`from m import f as g` calls the function it stands for",
     test_a_from_import_alias_calls_the_function_it_stands_for),
    ("a LIBRARY that calls its own import alias binds the defining name",
     test_a_library_that_CALLS_its_own_import_alias_binds_the_defining_name),
    ("an alias of a NON-exported name is refused by name",
     test_an_alias_of_a_non_exported_name_is_refused_by_name),
    ("a plain from-import keeps the bind audit's own message",
     test_a_plain_from_import_that_cannot_be_bound_is_still_the_audit_s),
    ("a relative import resolves and runs",
     test_a_relative_import_resolves_and_runs),
    ("a two-level relative import resolves and runs",
     test_a_two_level_relative_import_resolves_and_runs),
    ("a relative import behind an alias resolves and runs",
     test_a_relative_import_behind_an_alias_resolves_and_runs),
    ("a default argument crosses the boundary",
     test_a_default_argument_crosses_the_boundary),
    ("a keyword argument binds a cross-module callee by name",
     test_keyword_arguments_cross_the_boundary),
    ("a keyword naming no parameter is refused across the boundary",
     test_a_keyword_is_refused_by_name_across_the_boundary),
    ("a positional and a keyword on one parameter are refused",
     test_a_positional_and_a_keyword_on_one_parameter_are_refused),
    ("a host module's callee takes keywords out of order",
     test_a_host_module_call_takes_keywords),
    ("a keyword binds through the manifest when the source is gone",
     test_a_keyword_binds_through_the_manifest_when_the_source_is_gone),
    ("too many arguments across the boundary is refused",
     test_too_many_arguments_across_the_boundary_is_refused),
    ("too few arguments across the boundary is refused",
     test_too_few_arguments_across_the_boundary_is_refused),
    ("a re-exported callee called dotted obeys the same contract",
     test_a_re_exported_callee_obeys_the_same_contract_dotted),
    ("too many arguments to a re-exported callee is refused",
     test_too_many_arguments_to_a_re_exported_callee_is_refused),
    ("too few arguments to a re-exported callee is refused",
     test_too_few_arguments_to_a_re_exported_callee_is_refused),
    ("every argument count and a variadic agree with CPython",
     test_every_argument_count_and_a_variadic_agree_with_cpython),
    ("a local default and a cross-module default agree",
     test_a_local_default_and_a_cross_module_default_agree),
    ("a linked dylib's struct is usable with no import",
     test_a_linked_dylibs_struct_is_usable_with_no_import),
    ("a linked dylib whose source is gone is still refused",
     test_a_linked_dylib_whose_source_is_gone_is_still_refused),
    ("a gone source is refused however the construction spells itself",
     test_a_gone_source_is_refused_whatever_the_construction_spells),
    ("the manifest's call contract holds with no declaration to read",
     test_the_manifests_call_contract_holds_when_there_is_no_declaration),
    ("too many arguments with no declaration is refused",
     test_too_many_arguments_with_no_declaration_is_refused),
    ("too few arguments with no declaration is refused",
     test_too_few_arguments_with_no_declaration_is_refused),
    ("a default this image cannot materialize is refused",
     test_a_default_this_image_cannot_materialize_is_refused),
    ("a zero-argument construction runs a zero-required constructor",
     test_a_zero_argument_construction_runs_a_zero_required_constructor),
    ("a zero-argument construction of a constructor that needs arguments is "
     "refused",
     test_a_zero_argument_construction_of_a_constructor_that_needs_arguments),
    ("every exported function publishes a per-parameter frame contract",
     test_every_exported_function_publishes_a_per_parameter_contract),
    ("a frame address reaching an ordinary word names the contract, not the "
     "export",
     test_a_frame_address_reaching_an_ordinary_word_names_the_contract),
    ("arm64 and x86-64 return the same verdicts",
     test_the_executors_answer_the_same_questions),
    ("a container-returning export whose helpers take the buffer it passes them",
     test_a_container_returning_export_whose_helpers_take_the_buffer),
]

# A known failure is registered here, never hidden: `expect=` is a promise with
# a reason attached, and a marker nobody revisits is a bug quietly reintroduced.
EXPECTED_FAILURES: dict = {}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: the formal output is arm64, host is {platform.machine()}")
        return 0

    passed = failed = expected = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, fn in TESTS:
            expect = EXPECTED_FAILURES.get(name)
            try:
                fn(tmpdir, None)
            except TestFailure as e:
                if expect is not None:
                    expected += 1
                    print(f"  EXPECTED  {name}\n        {expect}")
                    continue
                failed += 1
                print(f"  FAIL  {name}\n        {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                continue
            except Exception as e:                      # noqa: BLE001
                if expect is not None:
                    expected += 1
                    print(f"  EXPECTED  {name}\n        {expect}")
                    if args.verbose:
                        import traceback
                        traceback.print_exc()
                    continue
                failed += 1
                print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                continue
            if expect is not None:
                failed += 1
                print(f"  FAIL  {name}\n        marked expect=… but it PASSES "
                      f"— drop the marker:\n        {expect}")
                continue
            passed += 1
            print(f"  PASS  {name}")

    stale = sorted(set(EXPECTED_FAILURES) - {n for n, _f in TESTS})
    for name in stale:
        print(f"  STALE  {name}\n        marked expect=… but is not in TESTS "
              f"— drop the marker")
        failed += 1

    print(f"\nformal cross-module: PASS={passed} EXPECTED={expected} "
          f"FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _drop_cas_home()
