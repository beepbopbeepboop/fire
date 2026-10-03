#!/usr/bin/env python3
"""Build `tempfile` for the formal backend and RUN it, compared with CPython.

    python3 test_formal_tempfile.py [-v] [group ...]

Why an oracle and not a table. Every answer below is computed twice — once
through `python3 fire.py build --formal --no-prove` and executed, once through
`tempfile` in this process — and the two have to agree. Nothing here states
what `gettempdir()` returns; it asks, because the answer is this machine's
`TMPDIR` and a table of it would be a table of the machine that wrote it.

## What is differential and what is not, and why

`gettempdir()` is **differentially** tested: it is a function of the
environment, both sides read the same environment, and the two answers must be
the same string. That is the whole claim the module makes.

`mkdtemp()` is **not**, and cannot be: the six characters in the middle of the
name are random on both sides, so no two runs of `mkdtemp` agree with each
other, let alone across processes. What is checked instead is CPython's set of
INVARIANTS on its own answer — the path exists, it is a directory, its parent is
`gettempdir()`, its last component starts with the prefix, its mode is `0o700`,
two calls differ — each one computed from CPython's own `mkdtemp` in this
process rather than written down here. An invariant is the right instrument for
a value neither side can predict, and it is what catches a model that returns
`""`, a path in the wrong place, or a name that ignored the prefix.

## Groups

  reachable  `tempfile` is answered: not in `HOST_UNREACHABLE`, resolvable, and
             a caller spelling the measured surface builds on BOTH backends
  tempdir    `gettempdir` against CPython's own, and the candidate order
  mkdtemp    the real `mkdtemp(3)`, against CPython's invariants
  absent     what the module does NOT answer, and that the refusal says so

`formal/hostmods/tempfile.mojo`'s docstring is the design; this file is its
ratchet. It runs on both architectures because a hostmod is a dylib and a dylib
is emitted twice, and "it works on the one I happened to run" is not a claim
about the module.
"""
import argparse
import os
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
sys.path.insert(0, HERE)

from test_formal_dylib import TestFailure, check, run_fire  # noqa: E402
from test_formal_json import Failure  # noqa: E402  (one failure type, not two)

from formal import admitted as A  # noqa: E402
from formal import imports as I  # noqa: E402

BACKENDS = ("arm64", "x86_64")

# One build/run per name, so a failure names the operation rather than the
# program. `hash()` is not used for the file name: it is salted per process, so
# a stale image from a previous run could be picked up by a colliding name.
_SEQ = [0]


def _program(lines):
    """A whole program from a list of BODY lines.

    The preamble is here rather than at each call site because every program in
    this file is `import tempfile` plus a body, and a hand-written `def main()`
    in each of them is a chance to leave one out — which is a parse error rather
    than a test failure, so it would read as the model's fault.
    """
    return ["import tempfile", "", "def main() -> int:"] + list(lines)


def _run(label, lines, cas_root, backend="arm64"):
    """Build `lines` as one program and return `(exit status, stdout lines)`.

    The EXIT STATUS and not just the output, because one row below depends on
    an image that answers with a refusal: a program that stops cannot be told
    from one that printed nothing if only the lines are compared.
    """
    _SEQ[0] += 1
    src = os.path.join(cas_root, f"tf_{backend}_{_SEQ[0]}_{label}.mojo")
    out = os.path.join(cas_root, f"tf_{backend}_{_SEQ[0]}_{label}.aout")
    with open(src, "w") as f:
        f.write("\n".join(_program(lines)) + "\n")
    home = os.path.join(cas_root, "cas", backend, str(_SEQ[0]))
    os.makedirs(home, exist_ok=True)
    r = run_fire(["build", "--formal", "--no-prove", f"--backend={backend}",
                  "-o", out, src], env={"GMOJO_HOME": home})
    check(r.returncode == 0,
          f"{label} [{backend}]: the image did not build.\n    "
          f"{(r.stderr or r.stdout or '').strip()[-500:]}")
    check(os.path.isfile(out), f"{label} [{backend}]: no image at {out}")
    p = subprocess.run([out], capture_output=True, text=True, timeout=120,
                       cwd=HERE)
    return p.returncode, [ln for ln in p.stdout.split("\n") if ln != ""]


# ── reachable ────────────────────────────────────────────────────────────────

def group_reachable(tmpdir, cas_root, verbose):
    """`tempfile` is ANSWERED: out of `HOST_UNREACHABLE`, and a caller builds.

    The tier move is the claim `bugs/FORMAL_subprocess_row_measured_b7.md` §5
    sizes, and it is checkable without building anything: a name left in
    `HOST_UNREACHABLE` after its model lands is a name the sweep's reach line
    reports as "needs a host this image does not have" for a file that now
    builds, which is a false statement rather than a conservative one.

    The build half is the part that cannot be checked by reading a set: the 43
    files this reaches spell `mkdtemp(prefix=…)` and `gettempdir()`, and the
    keywords are the whole reason they bind.
    """
    check("tempfile" not in I.HOST_UNREACHABLE,
          "tempfile is still in HOST_UNREACHABLE. It was there for the "
          "`TMPDIR`-derived half of 'a terminal', and `TMPDIR` is a variable: "
          "`formal/hostmods/tempfile.mojo` is CPython's own candidate walk over "
          "`os.getenv` and the real `mkdtemp(3)`. An entry left behind is a "
          "claim that is false the moment the module that answers it is in the "
          "tree, and it feeds `host_module_tier`, so the sweep's reach line "
          "would go on filing 111 files under a fact about the target.")
    check(I.host_module_tier("tempfile") == "",
          f"tempfile reports tier {I.host_module_tier('tempfile')!r}; a written "
          "module with no admitted contract is in NO tier, which is what "
          "`shutil`, `platform` and `fcntl` all report")

    # The file is on disk AND is what the resolver finds. Two checks because
    # `resolve_module_path`'s first pass is the one that decides, and a file
    # that exists but is not what the resolver returns is the failure that
    # leaves every caller refused with a message about a missing module.
    hostmod = os.path.join(A.HOSTMODS_ROOT, "tempfile.mojo")
    check(os.path.isfile(hostmod), f"{hostmod} does not exist")
    resolved = I.resolve_module_path("tempfile", relative_to=HERE)
    check(resolved and os.path.abspath(resolved) == os.path.abspath(hostmod),
          f"`import tempfile` resolves to {resolved!r}, not to the model at "
          f"{hostmod}")

    # The call surface this tree actually spells, on both backends. 91 of the
    # 143 `tempfile.mkdtemp` call sites pass `prefix=` and nothing else, so that
    # is the row that matters; the `dir=` row is here because `dir` is the one
    # parameter that changes WHERE the answer lands, and a model that ignored it
    # would pass every other row here.
    for backend in BACKENDS:
        for label, body in _SURFACE:
            status, out = _run(label, body, cas_root, backend)
            check(status == 0,
                  f"{label} [{backend}]: exited {status} with {out}")
            check(out, f"{label} [{backend}]: printed nothing")
    if verbose:
        for backend in BACKENDS:
            print(f"    {backend}: {len(_SURFACE)} spelling(s) of the measured "
                  f"surface build and run")
    return True, (f"tempfile is out of HOST_UNREACHABLE, resolves to its model, "
                  f"and {len(_SURFACE)} measured spellings build on "
                  f"{len(BACKENDS)} backends")


# The surface `group_reachable` builds, in the SPELLING this repository uses.
# The keywords are the point, so each row is the call as the tree writes it.
_SURFACE = [
    ("gettempdir", ['    printf("%s\\n", tempfile.gettempdir())']),
    ("mkdtemp-prefix", [
        '    printf("%s\\n", tempfile.mkdtemp(prefix="gmojo_tf_"))']),
    ("mkdtemp-plain", ['    printf("%s\\n", tempfile.mkdtemp())']),
    ("mkdtemp-dir", [
        '    printf("%s\\n", tempfile.mkdtemp(prefix="gmojo_tf_", dir="/tmp"))']),
    ("mkdtemp-dir-bad", [
        '    printf("[%s]\\n", tempfile.mkdtemp(dir="/tmp/gmojo_no_such_dir"))']),
]


# ── tempdir ──────────────────────────────────────────────────────────────────

def group_tempdir(tmpdir, cas_root, verbose):
    """`gettempdir` against CPython's own, and the ORDER of the walk.

    This is the one place in the module where the two sides can be expected to
    print the same string, so it is the strongest thing here: same process
    environment, same machine, same answer required.

    The order row is separate because it is the part most likely to rot: a walk
    that checks `/tmp` before `$TMPDIR` agrees with CPython whenever `TMPDIR` is
    unset, and disagrees on every host that sets it — which is every host this
    project's own tests run on, because the harness sets `TMPDIR`. So the walk
    is also checked with `$TMPDIR` set to a directory of this test's own, which
    is the case that separates "first candidate" from "first ENVIRONMENT
    candidate".
    """
    for backend in BACKENDS:
        _status, out = _run("tempdir", ['    printf("%s\\n", tempfile.gettempdir())'],
                            cas_root, backend)
        want = tempfile.gettempdir()
        check(out == [want],
              f"gettempdir [{backend}]: image {out}, CPython [{want!r}]. The "
              f"walk is CPython's candidate list in CPython's order — "
              f"$TMPDIR, $TEMP, $TMP, /tmp, /var/tmp, /usr/tmp, getcwd() — and "
              f"the first writable one wins. Both sides read the same "
              f"environment, so any difference is the ORDER, not the machine.")

    # The order row: a directory of this test's own, named by the environment.
    probe = tempfile.mkdtemp(prefix="gmojo_order_")
    os.chmod(probe, 0o700)
    _SEQ[0] += 1
    try:
        for backend in BACKENDS:
            src = os.path.join(cas_root, f"order_{backend}.mojo")
            out_path = os.path.join(cas_root, f"order_{backend}.aout")
            with open(src, "w") as f:
                f.write("\n".join(_program(
                    ['    printf("%s\\n", tempfile.gettempdir())'])) + "\n")
            home = os.path.join(cas_root, "cas", backend, "order")
            os.makedirs(home, exist_ok=True)
            r = run_fire(["build", "--formal", "--no-prove",
                          f"--backend={backend}", "-o", out_path, src],
                         env={"GMOJO_HOME": home})
            check(r.returncode == 0,
                  f"the $TMPDIR row [{backend}] did not build:\n    "
                  f"{(r.stderr or r.stdout or '').strip()[-400:]}")
            p = subprocess.run([out_path], capture_output=True, text=True,
                               timeout=120, cwd=HERE,
                               env={"TMPDIR": probe})
            check(p.stdout.strip() == probe,
                  f"with $TMPDIR={probe!r} the image answered "
                  f"{p.stdout.strip()!r}. The walk checks the ENVIRONMENT "
                  f"before /tmp, and this host sets TMPDIR, so a walk that "
                  f"checked /tmp first would agree with CPython on a host that "
                  f"does not and disagree here — which is the whole test.")
    finally:
        os.rmdir(probe)

    # The premise of the whole group: CPython's own answer is the directory the
    # walk should pick, and it is writable. Asserted rather than assumed, because
    # a machine with no writable candidate would make every row above vacuous.
    want = tempfile.gettempdir()
    check(os.path.isdir(want) and os.access(want, os.W_OK),
          f"CPython's own gettempdir() is {want!r} and it is not a writable "
          f"directory, so every comparison in this group would be against a "
          f"vacuous premise")
    if verbose:
        print(f"    gettempdir matches CPython on {len(BACKENDS)} backends; "
              f"the $TMPDIR row is checked separately because it is the one "
              f"that separates 'first candidate' from 'first environment one'")
    return True, ("gettempdir agrees with CPython on both backends, including "
                  "with $TMPDIR set to a directory of this test's own")


# ── mkdtemp ──────────────────────────────────────────────────────────────────

def _cp_invariants(path, prefix):
    """CPython's own invariants on `tempfile.mkdtemp`'s answer, recomputed here.

    Read off a REAL `mkdtemp` call rather than written as a table, for the
    reason this file's header gives: a table of expected values with a
    transposed row looks like a pass, and these are exactly the values a
    transposed row would hide.
    """
    # NOT the name itself, and the omission is the point: CPython's random
    # component is eight characters and `mkdtemp(3)`'s is six, so `name` cannot
    # be equal between the two answers and a row that compared it would be
    # failing on the one thing neither side can predict. What IS comparable is
    # everything the name is BUILT from: the directory it went into, the prefix
    # it carries, and the mode the C library gave it.
    return {
        "exists": os.path.isdir(path),
        "parent": os.path.dirname(path),
        "startswith": os.path.basename(path).startswith(prefix),
        "no template left": "XXXXXX" not in os.path.basename(path),
        "mode": stat.S_IMODE(os.stat(path).st_mode) if os.path.isdir(path) else -1,
    }


def group_mkdtemp(tmpdir, cas_root, verbose):
    """The real `mkdtemp(3)`, against CPython's invariants on its own answer.

    Six invariants, and each is asked of CPython's `mkdtemp` in THIS process
    first, so the model is compared with CPython rather than with a table:

      * the path EXISTS and is a directory — a `""` answer fails here;
      * its PARENT is `gettempdir()`, so the default `dir` is honoured;
      * its last component STARTS WITH the prefix, so `prefix` reaches libc;
      * its MODE is `0o700`, so the C library's own permissions are what came
        back and not something this module chose;
      * TWO CALLS DIFFER, which is the property that makes the name safe, and
        whose premise (CPython's own two calls differ) is asserted too;
      * a `dir` that does not exist gives CPython an `OSError` and gives the
        model `""` — the documented flattening of FORMAL.md phase 7, asserted
        as a DIFFERENCE rather than skipped, because that is the one place the
        two answers are supposed to differ and a future reader needs to see
        which side is which.
    """
    prefix = "gmojo_inv_"
    for backend in BACKENDS:
        _status, out = _run(
            "mkdtemp-inv",
            ['    d = tempfile.mkdtemp(prefix="%s")' % prefix,
             '    printf("d=%s\\n", d)'], cas_root, backend)
        check(len(out) == 1, f"mkdtemp [{backend}]: printed {out}")
        got = out[0][len("d="):]

        ref = tempfile.mkdtemp(prefix=prefix)
        want = _cp_invariants(ref, prefix)
        again = tempfile.mkdtemp(prefix=prefix)
        check(os.path.basename(again) != os.path.basename(ref),
              "the premise of the 'two calls differ' row: CPython's own two "
              "mkdtemp calls returned the same path, so the property this row "
              "checks is not a property of mkdtemp at all")
        try:
            bad = []
            if not os.path.isdir(got):
                bad.append(f"{got!r} is not an existing directory")
            else:
                got_inv = {
                    "parent": os.path.dirname(got),
                    "startswith": os.path.basename(got).startswith(prefix),
                    "no template left": "XXXXXX" not in os.path.basename(got),
                    "mode": stat.S_IMODE(os.stat(got).st_mode),
                }
                for k in ("parent", "startswith", "no template left", "mode"):
                    if got_inv[k] != want[k]:
                        bad.append(f"{k}: model {got_inv[k]!r}, CPython "
                                   f"{want[k]!r}")
            # `parent` is CPython's parent, which is CPython's gettempdir() —
            # and `group_tempdir` has already asserted the model's gettempdir()
            # is that string on this backend.
            check(not bad,
                  f"mkdtemp's answer disagrees with CPython's invariants "
                  f"[{backend}]:\n    " + "\n    ".join(bad))
            other = _run("mkdtemp-inv2",
                         ['    printf("%s\\n", tempfile.mkdtemp(prefix="'
                          + prefix + '"))'], cas_root, backend)[1]
            check(other and other[0] != got,
                  f"two model calls returned the same path ({other}), so the "
                  f"name is not fresh and a caller that makes two scratch "
                  f"directories would share one. CPython's two calls differ, "
                  f"which is asserted above.")
        finally:
            if os.path.isdir(got):
                os.rmdir(got)
            os.rmdir(ref)
            os.rmdir(again)

        # The refusal row: a `dir` that is not there.
        bad_dir = "/tmp/gmojo_no_such_dir_xyz"
        _status, out = _run(
            "mkdtemp-baddir",
            ['    printf("[%%s]\\n", tempfile.mkdtemp(dir="%s"))' % bad_dir],
            cas_root, backend)
        check(out == ["[]"],
              f"mkdtemp(dir={bad_dir!r}) [{backend}] answered {out}, and the "
              f"documented answer is the empty string — the model's own "
              f"flattening of CPython's FileNotFoundError, since this path has "
              f"no exception to raise")
        cp_raised = None
        try:
            tempfile.mkdtemp(dir=bad_dir)
        except OSError as e:
            cp_raised = type(e).__name__
        check(cp_raised is not None,
              f"CPython's mkdtemp(dir={bad_dir!r}) did NOT raise, so the row "
              f"above is asserting a divergence that does not exist and the "
              f"model's empty string would be a wrong answer")

    # THE SUFFIX LIMITATION, pinned. `mkdtemp(3)` substitutes the last six
    # bytes and nothing else, so `prefix + "XXXXXX" + suffix` is taken
    # LITERALLY when a suffix follows it — `mkdtemps(3)` is the entry point that
    # takes a suffix length, and it is the callee
    # `bugs/FORMAL_a_bare_c_call_returning_a_32_bit_int_is_compared_as_a_zero_extended_word.md`
    # shows is mis-compared. Asserted HERE so the divergence is a test and not
    # something the next caller of `mkdtemp(suffix=…)` discovers.
    for backend in BACKENDS:
        _status, out = _run(
            "mkdtemp-suffix",
            ['    printf("%s\\n", tempfile.mkdtemp(prefix="gmojo_sfx_", '
             'suffix=".txt"))'], cas_root, backend)
        check(len(out) == 1, f"the suffix row [{backend}] printed {out}")
        got = out[0]
        check(got.endswith(".txt"),
              f"mkdtemp(suffix='.txt') [{backend}] answered {got!r}, which "
              f"does not end in the suffix")
        check(got.count("XXXXXX") == 1,
              f"mkdtemp(suffix='.txt') [{backend}] answered {got!r}. The six "
              f"X's are expected to SURVIVE, because mkdtemp(3) substitutes "
              f"the last six bytes and `.txt` is not six of them. That is a "
              f"divergence from CPython and it is the documented one; if this "
              f"row starts failing because someone wired up mkstemps(3), then "
              f"the return-value bug is fixed and the suffix works — update "
              f"the module docstring in the same commit.")
        if os.path.isdir(got):
            os.rmdir(got)
    if verbose:
        print(f"    6 invariants x {len(BACKENDS)} backends, against CPython's "
              f"own mkdtemp; the suffix divergence pinned")
    return True, (f"mkdtemp's answer satisfies CPython's own six invariants on "
                  f"{len(BACKENDS)} backends, and the documented non-empty-"
                  f"suffix divergence is pinned")


# ── absent ───────────────────────────────────────────────────────────────────

# What this tree spells of `tempfile` that the model deliberately does not
# answer, with the reason. The counts are `ast` over every `.py` in the tree and
# `test_the_modelled_surface_covers_what_the_tree_spells` in
# `test_formal_admitted.py` is the same idea for `subprocess`.
_ABSENT = {
    "TemporaryDirectory": "a context manager and a class (142 call sites)",
    "NamedTemporaryFile": "a file object, i.e. a stream (64)",
    "TemporaryFile": "a stream (3)",
    "mkstemp": "reachable, but its only failure check is the comparison "
               "FORMAL_a_bare_c_call_returning_a_32_bit_int_is_compared_as_a_"
               "zero_extended_word.md shows to be false (3)",
}

# The counts `formal/hostmods/tempfile.mojo`'s table quotes, pinned against the
# source. The module docstring says these numbers and this file says they are
# what the source says, which is the only way a table in a docstring cannot go
# stale quietly.
#
# The population is `_repo_sweep_files()`, which EXCLUDES this file — so these
# are 92 and 1, not the 96 and 3 a walk that includes this file reports.  The
# difference is this file's own four `mkdtemp` calls and two `gettempdir` calls,
# and the first version of this ratchet counted them and then failed on its own
# number, which is the clearest statement of the rule: a measurement must not
# move the thing it measures.
_SPELLED_COUNTS = {
    "TemporaryDirectory": 142,
    "mkdtemp": 92,
    "NamedTemporaryFile": 64,
    "TemporaryFile": 3,
    "mkstemp": 3,
    "gettempdir": 1,
}
_REACHABLE_ONLY_FILES = 44
_IMPORTING_FILES = 128


def group_absent(tmpdir, cas_root, verbose):
    """What the model does NOT answer, and that a caller is told so.

    Three things, and the third is the one that matters. An absent name that
    produces "exports no such name" is a refusal a reader can act on; an absent
    name that produces a LINK error is a wrong answer, and an absent name that
    produces nothing at all is worse. So each row here builds a real caller and
    requires the refusal to NAME THE MODULE, which is what makes
    `formal/hostmods/tempfile.mojo`'s "what is not here" section checkable
    instead of a promise.

    The counts in `_ABSENT` are asserted against the source, because they are
    the number that sizes the row: a reader deciding whether to write the
    missing half needs to know 84 of the 127 files are still refused and why.
    """
    import ast
    for name, _why in sorted(_ABSENT.items()):
        src = os.path.join(cas_root, f"absent_{name}.mojo")
        out = os.path.join(cas_root, f"absent_{name}.aout")
        with open(src, "w") as f:
            f.write(f"import tempfile\n\ndef main() -> int:\n"
                    f"    printf(\"%s\\n\", tempfile.{name}())\n"
                    f"    return 0\n")
        r = run_fire(["build", "--formal", "--no-prove", f"--backend=arm64",
                      "-o", out, src],
                     env={"GMOJO_HOME": os.path.join(cas_root, "cas", "absent")})
        check(r.returncode != 0,
              f"a caller spelling `tempfile.{name}` BUILT, and the module's "
              f"docstring says it is absent. Either the docstring is stale or "
              f"the name appeared, and the two are different bugs.")
        msg = (r.stderr or r.stdout or "")
        check("tempfile" in msg,
              f"`tempfile.{name}` was refused with a message that does not name "
              f"the module: {msg.strip()[:300]}")

    # The SIZING, from the source rather than from the docstring, and over the
    # SAME population the docstring measured — the repository half of the
    # sweep's scope, which is what `_repo_sweep_files` names.
    counts, importing = _count_spelled()
    drifted = sorted((n, counts.get(n, 0), want)
                     for n, want in _SPELLED_COUNTS.items()
                     if counts.get(n, 0) != want)
    check(not drifted,
          "a `tempfile.<name>` count moved and the module docstring quotes the "
          "old one:\n    " + "\n    ".join(
              f"{n}: source says {got}, docstring says {want}"
              for n, got, want in drifted)
          + "\n  Either the call sites changed or the docstring's table is "
            "stale, and the number decides this row's worth.")
    check(importing == _IMPORTING_FILES,
          f"{importing} files import `tempfile` and the module docstring says "
          f"{_IMPORTING_FILES}")
    only_reachable = _files_using_only()
    check(only_reachable == _REACHABLE_ONLY_FILES,
          f"{only_reachable} files use only the reachable half of `tempfile` "
          f"and the docstring says {_REACHABLE_ONLY_FILES}. That is the number "
          f"the row is worth, so if it moved both documents have to.")
    if verbose:
        print(f"    {len(_ABSENT)} absent name(s) each refused naming the "
              f"module; {only_reachable} files reachable")
    return True, (f"{len(_ABSENT)} absent name(s) are refused naming the "
                  f"module, and the {only_reachable}-file yield the row's "
                  f"measurement claims is still {only_reachable}")


# This file, out of the population the census measures. **A measurement must
# not move the thing it measures**, and this one calls `tempfile.mkdtemp` and
# `tempfile.gettempdir` in three places, so leaving it in would make every
# case added here move `mkdtemp`'s count and then fail — which is what happened
# the first time: the count read 97 against a docstring that said 96, and the
# ratchet was right and the population was wrong.  The census is about the
# CALLERS a module is written for, and this file is not a caller.
_SELF = os.path.basename(os.path.abspath(__file__))


def _repo_sweep_files():
    """The REPO half of the sweep's scope, MINUS this file, and only the repo.

    `tools/formal_sweep.py`'s default scope is this repository plus the
    external stdlib tree, and the stdlib's `std/` has no `import tempfile` in
    it — so the two counts differ only by the handful of stdlib files that do,
    and the numbers `formal/hostmods/tempfile.mojo`'s docstring and
    `bugs/FORMAL_subprocess_row_measured_b7.md` §5 quote were measured over the
    REPO. Asserting against a different population would make this file's
    ratchet disagree with the prose it is a ratchet for, so the population is
    named here rather than left to whichever default is in scope.
    """
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import formal_sweep as S
    return [p for p in S.find_source_files([HERE])
            if os.path.basename(p) != _SELF]


def _count_spelled():
    """`({name: n}, n_importing_files)` — every `tempfile.<name>` this tree spells.

    The SECOND number is the files that actually `import tempfile`, which is not
    the number of files whose text contains the string: one file in this
    repository mentions it in a comment, and counting that would make the
    docstring's "128 files import it" a number about a comment.
    """
    import ast
    import warnings
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import formal_sweep as S
    counts = {}
    importing = 0
    for path in _repo_sweep_files():
        imported_here = False
        try:
            with warnings.catch_warnings():
                # A `.py` in the tree with a regex in a docstring emits a
                # SyntaxWarning under 3.14, and it is that file's business.
                warnings.simplefilter("ignore")
                tree = ast.parse(open(path, encoding="utf-8",
                                      errors="replace").read())
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "tempfile"):
                counts[node.attr] = counts.get(node.attr, 0) + 1
            elif (isinstance(node, ast.Import)
                    and any(a.name == "tempfile" for a in node.names)):
                imported_here = True
        if imported_here:
            importing += 1
    return counts, importing


def _files_using_only():
    """How many swept files use ONLY `mkdtemp`/`mkstemp`/`gettempdir`.

    The number the row is worth, and the one measurement that decides whether
    writing `tempfile` was worth a day: a file in this set moves out of
    `not-answerable/host-import` and into the answerable denominator the moment
    the model lands, and a file outside it does not move at all.
    """
    import ast
    import warnings
    reachable = {"mkdtemp", "mkstemp", "gettempdir"}
    n = 0
    for path in _repo_sweep_files():
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "import tempfile" not in src:
            # A cheap pre-filter, and it is a SUBSTRING test: one file in this
            # repository mentions the module in a comment and does not import
            # it, which is why the count of files that import it is a separate
            # number from the length of this loop's output.
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = ast.parse(src)
        except (SyntaxError, ValueError):
            continue
        used = {node.attr for node in ast.walk(tree)
                if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "tempfile")}
        if used and used <= reachable:
            n += 1
    return n


GROUPS = {
    "reachable": group_reachable,
    "tempdir": group_tempdir,
    "mkdtemp": group_mkdtemp,
    "absent": group_absent,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="run only these groups")
    args = ap.parse_args()
    if args.groups:
        unknown = [g for g in args.groups if g not in GROUPS]
        if unknown:
            print(f"unknown group(s): {unknown}; have {sorted(GROUPS)}")
            return 2

    cas_root = tempfile.mkdtemp(prefix="formal_tempfile_")
    passed = failed = 0
    try:
        for gname in (args.groups or list(GROUPS)):
            fn = GROUPS[gname]
            try:
                _ok, note = fn(cas_root, cas_root, args.verbose)
            except (TestFailure, Failure) as e:
                failed += 1
                print(f"  FAIL  {gname}\n        {e}")
                continue
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"  ERROR {gname}\n        {type(e).__name__}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                continue
            passed += 1
            print(f"  PASS  {gname}\n        {note}")
    finally:
        import shutil
        shutil.rmtree(cas_root, ignore_errors=True)

    print(f"\nformal tempfile: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())