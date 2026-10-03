#!/usr/bin/env python3
r"""Build `formal/hostmods/fcntl.mojo` and RUN it against CPython's `fcntl`.

    python3 test_formal_fcntl.py [-v] [group ...]

Groups: `consts`, `flock`, `fdflags`, `independence`, `resolve`, `absent`.
With no argument, all.

WHY THIS MODULE EXISTS AT ALL, AND WHAT IT IS WORTH
--------------------------------------------------
One line, spelled the same way in the three files that want it
(`tools/ab_run_one.py:105`, `tools/control.py:66`, `tools/integrate.py:181`):

    fcntl.flock(fd, fcntl.LOCK_EX)

**It is worth ZERO files to PASS.** All three of those files also import
`subprocess`, so all three move from "blocked on a module that could be written"
to "blocked on a second process", which is a fact about the target with an owner
rather than one with none. That is the same accounting
`bugs/FORMAL_platform_reachable_row_measured.md` §2 records for the `platform`
row, and it is stated here so that a future reader does not count this module as
a coverage improvement.

THE TWO PROPERTIES OF A LOCK THAT A LOCK MODULE GETS WRONG
---------------------------------------------------------
Both are asserted, and both are the reason this test is not a table of constants
with a smoke test on top:

  * **A LOCK IS PER OPEN FILE DESCRIPTION, NOT PER PROCESS.** So a process that
    holds a lock on one descriptor must be REFUSED on a second descriptor it
    opened itself, if the second one asks for the same lock. A `flock`
    implemented over POSIX record locks (`F_SETLK` with `l_pid == 0`, which
    means the calling process) would pass every single-process test and be wrong
    against every other process on the machine. `self_conflict` asserts the
    refusal.
  * **`flock` AND `F_SETLK` DO NOT INTERACT — ON LINUX. ON macOS THEY DO**, and
    that is measured rather than assumed: with CPython holding a `F_WRLCK`, a
    `flock` on another descriptor is refused, because macOS implements `flock`
    over `fcntl` record locks with a different `l_type`. `independence` asserts
    the macOS answer, so the platform difference is pinned in a test rather than
    in a comment somebody will get backwards.

EVERY OPERATION IS OR'd WITH `LOCK_NB`, in every case, without exception. That is
not tidiness: without `LOCK_NB` a contended lock BLOCKS, and on this path a
blocked call is an image that stops with no output, which the harness can only
report as a timeout.

BOTH ARCHITECTURES
------------------
Built and run for arm64 and for x86-64 and the two answers compared with each
other as well as with CPython; the runner is `test_formal_dylib.py`'s
`build_and_run`, shared with `test_formal_stat.py`, `test_formal_math.py` and
`test_formal_shutil.py`.
"""
import argparse
import fcntl as CPY
import os
import platform
import subprocess
import sys
import tempfile

import test_formal_dylib as D        # noqa: E402  (shared two-backend runner)

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 900

# Every integer CPython's `fcntl` exports, as NAMES. Read off the live module,
# so the oracle is the interpreter's own value and not a number written here —
# which is the only reason the `consts` group can claim to be a mirror.
CONSTANTS = [n for n in sorted(dir(CPY))
             if n.startswith(("F_", "LOCK_", "FD_"))
             and isinstance(getattr(CPY, n), int)]

# The names this module documents as absent, each with the reason in
# `formal/hostmods/fcntl.mojo`. An omission that is not pinned cannot be told
# from an implementation by any reader of that file.
ABSENT = {
    "ioctl": "a device's private protocol; there is no driver on this image",
    "lockf": "the third argument of fcntl(2) is a POINTER through a variadic "
             "tail, and a variadic pointer argument cannot be spelled here; the "
             "tail itself now works, which is what the four descriptor-flag "
             "calls in the fdflags group are the evidence for",
}


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


def backends():
    if not D.host_machine():
        return []
    ok, why = D.rosetta()
    if not ok:
        print(f"note: x86-64 half SKIPPED — {why}")
        return ["arm64"]
    return list(D.BACKENDS)


# ── the groups ──────────────────────────────────────────────────────────────

def group_consts(tmpdir, archs, verbose):
    """Every integer CPython's `fcntl` exports, against CPython's own value.

    The whole of `formal/hostmods/fcntl.mojo` that is not `flock` is numbers, so
    this group is most of the module's content and it is checked name by name
    rather than by a table. `LOCK_NB`'s value in particular is load-bearing for
    every lock the module takes, and the comment at `LOCK_NB` says that a caller
    must OR it in — which is only checkable if the number is right.
    """
    src = ["import fcntl", "", "def main() -> int:"]
    for name in CONSTANTS:
        src.append(f'    printf("{name}=%lld@@", fcntl.{name}())')
    want = {name: str(getattr(CPY, name)) for name in CONSTANTS}

    def compare(arch, recs):
        got = dict(rec.split("=", 1) for rec in recs if "=" in rec)
        bad = [f"{k}: image {got.get(k)!r}, CPython {v!r}"
               for k, v in want.items() if got.get(k) != v]
        check(not bad, f"[{arch}] {len(bad)} of {len(want)} constants differ "
                       f"from CPython's `fcntl`: " + "; ".join(bad))

    D.build_and_run("\n".join(src) + "\n", "fcntl_consts", tmpdir, compare,
                    backends=archs)
    if verbose:
        print(f"    {len(CONSTANTS)} constants, each against CPython's own")
    return True, f"{len(CONSTANTS)} constants agree with CPython's fcntl"


def group_flock(tmpdir, archs, verbose):
    """`flock` itself, over the sequence that separates every case.

    In order, on ONE descriptor: take it exclusively, ask for it again
    non-blocking (0 — the same open file description already holds it), unlock,
    take it again, and ask again non-blocking (0 again). Then the same
    non-blocking request on a SECOND descriptor of the same file, which is the
    `self_conflict` case and the one a POSIX-record-lock implementation gets
    wrong. Then `LOCK_SH` on two descriptors at once, and the release.

    CPython's answers come from the same sequence in this process on the same
    file, which is the only way the comparison is about the lock and not about
    the file.
    """
    src = """\
from fcntl import flock, LOCK_EX, LOCK_SH, LOCK_UN, LOCK_NB
from os._syscalls import fs_open_ro, fs_close

def main(n):
    var a = fs_open_ro("lockfile")
    var b = fs_open_ro("lockfile")
    printf("open_a=%lld@@", a >= 0)
    printf("open_b=%lld@@", b >= 0)
    printf("ex=%lld@@", flock(a, LOCK_EX()))
    printf("ex_again=%lld@@", flock(a, LOCK_EX() | LOCK_NB()))
    printf("un=%lld@@", flock(a, LOCK_UN()))
    printf("ex2=%lld@@", flock(a, LOCK_EX()))
    printf("ex2_nb=%lld@@", flock(a, LOCK_EX() | LOCK_NB()))
    printf("other_ex_nb=%lld@@", flock(b, LOCK_EX() | LOCK_NB()))
    printf("unlock_b=%lld@@", flock(b, LOCK_UN()))
    printf("after=%lld@@", flock(b, LOCK_EX() | LOCK_NB()))
    printf("other_ex=%lld@@", flock(b, LOCK_EX() | LOCK_NB()))
    printf("other_un=%lld@@", flock(b, LOCK_UN()))
    printf("a_ex_nb=%lld@@", flock(a, LOCK_EX() | LOCK_NB()))
    printf("sh_a=%lld@@", flock(a, LOCK_SH() | LOCK_NB()))
    printf("sh_b=%lld@@", flock(b, LOCK_SH() | LOCK_NB()))
    printf("sh_ex_b=%lld@@", flock(b, LOCK_EX() | LOCK_NB()))
    printf("sh_un_a=%lld@@", flock(a, LOCK_UN()))
    printf("sh_un_b=%lld@@", flock(b, LOCK_UN()))
    printf("bad_fd=%lld@@", flock(999, LOCK_EX() | LOCK_NB()))
    fs_close(a)
    fs_close(b)
    return 0
"""
    for arch in archs:
        work = _lock_dir(tmpdir, "flock_" + arch)
        want = _flock_oracle(work)

        def compare(a, recs, want=want):
            got = dict(_recs(recs))
            bad = [f"{k}: image {got.get(k)!r}, CPython {v!r}"
                   for k, v in want.items() if got.get(k) != v]
            check(not bad, f"[{a}] {len(bad)} of {len(want)} `flock` answers "
                           f"differ from CPython's:\n      " +
                           "\n      ".join(bad))
            # the self-conflict case, said separately so a failure names it
            check(got.get("other_ex_nb") == "-1",
                  f"[{a}] a SECOND descriptor of the same file was not "
                  f"refused {got.get('other_ex_nb')!r}; a `flock` over POSIX "
                  f"record locks would say 0 here, because those are "
                  f"per-process and this is one process")

        D.build_and_run(src, "fcntl_flock", tmpdir, compare, backends=[arch],
                        cwd=work)
    if verbose:
        print(f"    {len(want)} answers over the take/retake/release sequence, "
              f"including the second-descriptor refusal, against CPython")
    return True, (f"{len(want)} flock answers agree with CPython, and a "
                  f"second descriptor of the same file is refused")


def _lock_dir(tmpdir, tag):
    work = os.path.join(tmpdir, tag)
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "lockfile"), "w") as f:
        f.write("lock\n")
    return work


def _flock_oracle(work):
    """CPython's answers for the `flock` sequence, on the same file.

    The SAME order as the program and the same descriptor arrangement — two
    descriptors this process opened itself on one file — because the sequence's
    meaning is in the arrangement. `BlockingIOError` is `None` here, which is
    the module's -1: there are no exceptions on this path, and the two failure
    reasons are not separable there because `errno` cannot be bound
    (`formal/hostmods/os/_syscalls.mojo`'s header).
    """
    p = os.path.join(work, "lockfile")
    a = os.open(p, os.O_RDONLY)
    b = os.open(p, os.O_RDONLY)
    got = {}

    def f(key, fd, op):
        # CPython's `fcntl.flock` returns `None` on success and RAISES on
        # failure, so the oracle has to translate both: `None` is this module's 0
        # and a raise is its -1. The first version wrote `str(CPY.flock(...))`
        # and compared `'None'` against `'0'`, so every successful lock in the
        # sequence reported a difference — which is what an oracle that records
        # a language's spelling instead of its VALUE costs.
        try:
            CPY.flock(fd, op)
            got[key] = "0"
        except BlockingIOError:
            got[key] = "-1"
        except OSError:
            got[key] = "-1"
    got["open_a"] = "1"
    got["open_b"] = "1"
    f("ex", a, CPY.LOCK_EX)
    f("ex_again", a, CPY.LOCK_EX | CPY.LOCK_NB)
    f("un", a, CPY.LOCK_UN)
    f("ex2", a, CPY.LOCK_EX)
    f("ex2_nb", a, CPY.LOCK_EX | CPY.LOCK_NB)
    f("other_ex_nb", b, CPY.LOCK_EX | CPY.LOCK_NB)
    f("unlock_b", b, CPY.LOCK_UN)
    f("after", b, CPY.LOCK_EX | CPY.LOCK_NB)
    f("other_ex", b, CPY.LOCK_EX | CPY.LOCK_NB)
    f("other_un", b, CPY.LOCK_UN)
    f("a_ex_nb", a, CPY.LOCK_EX | CPY.LOCK_NB)
    f("sh_a", a, CPY.LOCK_SH | CPY.LOCK_NB)
    f("sh_b", b, CPY.LOCK_SH | CPY.LOCK_NB)
    f("sh_ex_b", b, CPY.LOCK_EX | CPY.LOCK_NB)
    f("sh_un_a", a, CPY.LOCK_UN)
    f("sh_un_b", b, CPY.LOCK_UN)
    try:
        CPY.flock(999, CPY.LOCK_EX | CPY.LOCK_NB)
        got["bad_fd"] = "0"
    except OSError:
        got["bad_fd"] = "-1"
    os.close(a)
    os.close(b)
    return got


def group_independence(tmpdir, archs, verbose):
    """Does a `flock` here exclude a POSIX record lock? **MEASURED: NO, and
    the opposite of Linux.**

    This group was written on the assumption that `flock` and `F_SETLK` are two
    independent lock spaces — which is true on Linux and **is false on macOS**,
    where `flock` is implemented over `fcntl` record locks with a different
    `l_type` encoding and the two CONFLICT. Measured here: with CPython holding a
    `F_WRLCK` on one descriptor, the image's `flock` on another descriptor of the
    same file is REFUSED, returning -1. The first version of this group asserted
    the opposite (that the `flock` would succeed) on the strength of the Linux
    behaviour and failed on its first run.

    **So the assertion here is the one this platform gives**, and it is worth
    having for two reasons: it pins a platform difference that a reader who
    assumed Linux would get backwards, and it is the answer that distinguishes
    the two implementations of a lock. A `flock` written over POSIX record locks
    and a real `flock(2)` are indistinguishable in every other case in this file;
    this is the one where they differ from each other, and here they agree with
    each other because macOS made them the same lock.

    A cross-process version of this is not possible in this harness: the image
    holds the lock and EXITS, so by the time this process could ask, there would
    be no holder. The direction below — CPython holds, the image asks — is the
    one that can be done in one process, and it is the informative direction.
    """
    src = """\
from fcntl import flock, LOCK_EX, LOCK_UN, LOCK_NB
from os._syscalls import fs_open_ro, fs_close

def main(n):
    var a = fs_open_ro("lockfile")
    printf("flock_while_posix_locked=%lld@@", flock(a, LOCK_EX() | LOCK_NB()))
    printf("un=%lld@@", flock(a, LOCK_UN()))
    fs_close(a)
    return 0
"""
    for arch in archs:
        work = _lock_dir(tmpdir, "indep_" + arch)
        held = os.open(os.path.join(work, "lockfile"), os.O_RDWR)
        CPY.lockf(held, CPY.F_WRLCK, 0, 0, os.SEEK_SET)

        def compare(a, recs):
            got = dict(_recs(recs))
            check(got.get("flock_while_posix_locked") == "-1",
                  f"[{a}] a `flock` SUCCEEDED while a POSIX `F_WRLCK` was held "
                  f"on another descriptor: "
                  f"{got.get('flock_while_posix_locked')!r}. On macOS the two "
                  f"share a lock space — measured, and the opposite of Linux — "
                  f"so this is a platform answer and not a defect in either "
                  f"implementation")

        D.build_and_run(src, "fcntl_indep", tmpdir, compare, backends=[arch],
                        cwd=work)
        CPY.lockf(held, CPY.F_UNLCK, 0, 0, os.SEEK_SET)
        os.close(held)
    if verbose:
        print("    a flock IS refused by a POSIX record lock on the same file: "
              "macOS shares one lock space where Linux has two")
    return True, ("flock and F_SETLK share a lock space on macOS, measured "
                  "rather than assumed from Linux")


def group_resolve(tmpdir, archs, verbose):
    """`fcntl` resolves where `formal/imports.py` says, and is not a host module.

    **`fcntl` WAS IN NEITHER TIER**, and the group asserts that rather than
    assuming it: the sweep classified `import fcntl` as
    `not-answerable/host-import` because no `fcntl.mojo` existed for the resolver
    to find, not because a set said so, and `_is_host_module` returns False for
    it either way. So the refusal a caller got was the resolver's
    "not a stdlib or sibling module, and no such file exists" — the same message
    any unresolvable import gets — and there was nothing to remove. The assertion
    is kept because a future edit that ADDED `fcntl` to a tier would then refuse
    `import fcntl` after the module that answers it is in the tree, which is a
    false statement about the target rather than a conservative one.
    """
    import formal.imports as I
    path = os.path.join(HERE, "formal", "hostmods", "fcntl.mojo")
    check(os.path.isfile(path), "no Mojo source for fcntl")
    got = I.resolve_module_path("fcntl")
    check(got is not None and os.path.samefile(got, path),
          f"import fcntl resolves to {got!r}, not {path!r}")
    check(I.host_module_tier("fcntl") == "",
          "fcntl is in HOST_MODELLED or HOST_UNREACHABLE; its Mojo source "
          "exists, so either entry is now a false statement about the target")
    check(I._is_host_module("fcntl") is False,
          "fcntl is still classified as a host module, which would make "
          "`import fcntl` refuse for a module that now has Mojo source")
    if verbose:
        print("    resolves into formal/hostmods/, out of HOST_MODELLED, out "
              "of the host-module union")
    return True, "fcntl resolves, and left HOST_MODELLED"


def group_absent(tmpdir, archs, verbose):
    """Every name the module documents as absent, refused BY NAME.

    A CALL, not a bare name: a bare `fcntl.ioctl` is a read of a module-level
    name, refused for a different and vaguer reason that does not name the name
    being asked for.

    `lockf` is the interesting entry now, because its absence is NOT a fact
    about the target — the syscall is right there and the module could call it.
    It is a SPELLING: `fcntl`'s variadic tail works (the `fdflags` group is the
    evidence, and it is why `getfd`/`setfd`/`getfl`/`setfl` were removed from
    this table when they started working), and what `lockf` still cannot say is
    that the third argument is a POINTER. The docstring says so; the group is
    what stops a later reader from adding it back and believing the return
    value.
    """
    arch = archs[0]
    for name, _why in sorted(ABSENT.items()):
        args = "(1, 1, 0, 0, 0)" if name == "lockf" else "(1, 1)"
        src = ("import fcntl\\n\\ndef main() -> int:\\n"
               f"  fcntl.{name}{args}\\n  return 0\\n")
        path = os.path.join(tmpdir, "fcntl_absent_" + name + ".mojo")
        with open(path, "w") as f:
            f.write(src)
        out = os.path.join(tmpdir, "fcntl_absent_" + name + "." + arch)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "--backend=" + arch, "-o", out, path],
            capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
        check(not (r.returncode == 0 and os.path.isfile(out)),
              f"fcntl.{name} built, but the module documents it as absent — "
              f"either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout or ""
        check(name in msg,
              f"fcntl.{name} failed without naming itself: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(ABSENT)} absent names refused, each naming itself")
    return True, f"{len(ABSENT)} absent names refused"


def group_fdflags(tmpdir, archs, verbose):
    """`getfd`/`setfd`/`getfl`/`setfl`, against CPython's `fcntl` on the same file.

    These four were ABSENT, and their absence was the only thing in this module
    that was a spelling rather than a fact about the target: `fcntl(2)` is
    `int fcntl(int, int, ...)`, the third argument is variadic, and Apple arm64
    passes a variadic argument in a stack area rather than in an argument
    register. `formal/model.py`'s `VARIADIC_LIBC` is where a callee is recorded
    as variadic, `fcntl` was not in it, and so the third argument was emitted
    positionally into X2 and nothing was written into the area — where the
    syscall read whatever the caller had at `[sp]`. Measured before the entry
    existed: `setfd` reported success and changed nothing, and `getfl` reported
    192 where CPython reports 4.

    **x86-64 was never affected**, because SysV x86-64 passes variadic arguments
    in the same registers as fixed ones. So the group runs on every backend
    `backends()` offers and the two are compared with CPython rather than with
    each other, and a run that covered only the host's own architecture would
    have passed this before the fix as well as after it.

    The sequence CLEARS the flag word before reading it, and that is not tidiness
    — it is what makes every row comparable. CPython's `os.open` sets
    `FD_CLOEXEC` by default and this path's `open(p, "r")` does not and cannot
    (there is no `open` flag for it), so a fresh descriptor legitimately reads 0
    here and 1 under CPython. Clearing first puts both descriptors in the same
    state, so there is no row in this group that has to be excluded from the
    comparison and no "expected difference" that a later change could quietly
    widen.
    """
    src = """\
from fcntl import getfd, setfd, getfl, setfl, FD_CLOEXEC
from os._syscalls import fs_open_ro, fs_close

def main(n):
    var fd = fs_open_ro("lockfile")
    printf("clear=%lld@@", setfd(fd, 0))
    printf("zero=%lld@@", getfd(fd))
    printf("set=%lld@@", setfd(fd, FD_CLOEXEC()))
    printf("one=%lld@@", getfd(fd))
    printf("clear2=%lld@@", setfd(fd, 0))
    printf("back=%lld@@", getfd(fd))
    printf("fl0=%lld@@", getfl(fd))
    printf("setfl=%lld@@", setfl(fd, 4))
    printf("fl1=%lld@@", getfl(fd))
    fs_close(fd)
    return 0
"""
    for arch in archs:
        work = _lock_dir(tmpdir, "fdflags_" + arch)
        want = _fdflags_oracle(work)

        def compare(a, recs, want=want):
            got = dict(_recs(recs))
            bad = [f"{k}: image {got.get(k)!r}, CPython {v!r}"
                   for k, v in want.items() if got.get(k) != v]
            check(not bad, f"[{a}] {len(bad)} of {len(want)} descriptor-flag "
                           f"answers differ from CPython's:\n      " +
                           "\n      ".join(bad))

        D.build_and_run(src, "fcntl_fdflags", tmpdir, compare, backends=[arch],
                        cwd=work)
    if verbose:
        print(f"    {len(want)} descriptor-flag answers over the "
              f"clear/set/read sequence, against CPython's fcntl")
    return True, (f"{len(want)} getfd/setfd/getfl/setfl answers agree with "
                  f"CPython, so the variadic third argument arrives")


def _fdflags_oracle(work):
    """CPython's answers for the descriptor-flag sequence, on the same file.

    The same order as the program and the same starting state, which is what
    makes the two sets of rows comparable: CPython's `os.open` sets
    `FD_CLOEXEC` and this path's `open` cannot, so the first thing the sequence
    does is put both descriptors' word at 0.
    """
    fd = os.open(os.path.join(work, "lockfile"), os.O_RDONLY)
    got = {}
    got["clear"] = str(CPY.fcntl(fd, CPY.F_SETFD, 0))
    got["zero"] = str(CPY.fcntl(fd, CPY.F_GETFD))
    got["set"] = str(CPY.fcntl(fd, CPY.F_SETFD, CPY.FD_CLOEXEC))
    got["one"] = str(CPY.fcntl(fd, CPY.F_GETFD))
    got["clear2"] = str(CPY.fcntl(fd, CPY.F_SETFD, 0))
    got["back"] = str(CPY.fcntl(fd, CPY.F_GETFD))
    got["fl0"] = str(CPY.fcntl(fd, CPY.F_GETFL))
    got["setfl"] = str(CPY.fcntl(fd, CPY.F_SETFL, 4))
    got["fl1"] = str(CPY.fcntl(fd, CPY.F_GETFL))
    os.close(fd)
    return got


def _recs(recs):
    """`<key>=<value>` records as pairs. See `test_formal_shutil.py`'s."""
    out = []
    for rec in recs:
        k, _, v = rec.partition("=")
        out.append((k, v))
    return out


GROUPS = {
    "consts": group_consts,
    "flock": group_flock,
    "fdflags": group_fdflags,
    "independence": group_independence,
    "resolve": group_resolve,
    "absent": group_absent,
}


def main():
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
    archs = backends()
    failed = []
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR") or None) \
            as tmpdir:
        for n in names:
            try:
                ok, detail = GROUPS[n](tmpdir, archs, args.verbose)
            except Exception as e:
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            print(("PASS " if ok else "FAIL ") + n + (
                ("  " + detail) if detail else ""))
            if not ok:
                failed.append(n)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed "
          f"({', '.join(archs)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
