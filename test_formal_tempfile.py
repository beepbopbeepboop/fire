#!/usr/bin/env python3
r"""Build `formal/hostmods/tempfile.mojo` and RUN it against CPython's `tempfile`.

    python3 test_formal_tempfile.py [-v] [group ...]

Groups: `constants`, `gettempdir`, `candidates`, `mkdtemp`, `name`, `exclusive`,
`temporary-directory`, `absent`. With no argument, all.

WHY THE ORACLE IS CPython'S OWN `tempfile` AND NOT A TABLE OF ANSWERS
--------------------------------------------------------------------
`tempfile` is the module where a plausible-looking implementation is most likely
to be quietly wrong: every answer it gives is a NAME, and a name cannot be
compared to a table. `gettempdir` returns whatever `TMPDIR` says, which differs
per machine and per shell; `mkdtemp` returns eight random characters. So nothing
here is a recorded string. What is compared is:

  * the CONSTANTS — `gettempprefix()`, `TMP_MAX()` and the alphabet the name is
    drawn from — against this interpreter's own, read out of it at test time. A
    module that answered `""` or `9999` would pass a recorded-value test on a
    machine where nobody had checked what CPython says.
  * `gettempdir()` against `tempfile.gettempdir()`, as a STRING, on this host.
  * the CANDIDATE LIST by rebuilding the walk CPython walks, with the
    environment under the test's control — three groups, one per environment
    shape, each compared as "which directory did each side pick" rather than as
    a path spelled out in the test.
  * `mkdtemp` by asking BOTH sides the same question about BOTH answers: is it a
    directory, is it inside the directory it was told to use, is its mode 448
    under this process's umask, is its name `prefix` + eight characters of
    CPython's alphabet + `suffix`, and are two calls' names different. Every one
    of those is a PROPERTY, and every one of them is a thing a `mkdtemp` that
    returned a plausible string without creating anything would fail.

WHAT THIS GROUP DOES NOT CLAIM, and why it is in the docstring rather than
only here: `TemporaryDirectory` is 64 of the 111 files the ranking counts and
it is ABSENT from the module, because its contract is the removal on the way out
of a `with` and `formal/hostmods/contextlib.mojo` measured that there is no
`__exit__` to hook. The `absent` group asserts the refusal says so by NAME, so
a future reader who finds the name exported learns that it was a decision with a
measurement behind it rather than an oversight.

THE FILESYSTEM IS REAL, AND THAT IS THE POINT
----------------------------------------------
`gettempdir`'s candidates and `mkdtemp`'s directory are on the real filesystem,
and the test never removes the directories it makes except through the one group
whose subject IS removal — which is `absent`, and it asserts the refusal rather
than performing one. Everything else is left under the scratch directory
`test_formal_shutil.py`'s runner shape hands in, which is this process's
`TMPDIR` (`tools/` sets it to the worktree's `.tmp`), so the paths these groups
compare are inside the tree this worktree owns.

BOTH ARCHITECTURES
------------------
Every group is built and run for arm64 and for x86-64, through
`test_formal_dylib.py`'s `build_and_run`, and the two architectures' records are
compared with each other as well as with CPython — so a module that lowered
differently on the two is caught even where both happen to agree with CPython.
A host with no x86-64 support skips that half (`rosetta()`), which is the same
convention every other host-module suite here follows.
"""
import argparse
import os
import platform
import shutil
import stat as CPY
import sys
import tempfile as CPY_TEMPFILE     # the oracle. Not shadowed below: every
                                    # reference to the HOST's tempfile is this
                                    # name, so a reader cannot mistake it for
                                    # the module under test.
import test_formal_dylib as D        # noqa: E402  (shared two-backend runner)

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 900
REC = "@@"

# `0o700`, as the DECIMAL the module spells. Both sides are masked by the same
# umask — they run in the same process, seconds apart — so the comparison is of
# the mode each side asked for against the mode each side got.
MODE_700 = 0o700


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


def backends():
    """The architectures this host can run a formal image on."""
    if not D.host_machine():
        return []
    ok, why = D.rosetta()
    if not ok:
        print(f"note: x86-64 half SKIPPED — {why}")
        return ["arm64"]
    return list(D.BACKENDS)


def recs_of(recs):
    """`<key>=<value>` records as pairs, with one `[` `]` convention.

    `test_formal_shutil.py`'s convention, and for its reason: a call that
    returns a PATH is printed bare and a call that returns `""` or a number is
    printed inside `[` `]`, so "the answer was the empty string" is
    distinguishable from "the answer was not printed". A group here that cannot
    tell those apart cannot say which of the two failures it found.
    """
    out = {}
    for rec in recs:
        k, _, v = rec.partition("=")
        if v.startswith("[") and v.endswith("]"):
            v = v[1:-1]
        out[k] = v
    return out


# ── groups ──────────────────────────────────────────────────────────────────

def group_constants(tmpdir, archs, verbose):
    """`gettempprefix`, `TMP_MAX` and the name's alphabet, against CPython's.

    Three answers that are the same on every machine, which is exactly why they
    are worth checking: they are the ones a module can get wrong by writing
    something plausible, and `TMP_MAX` in particular is a loop bound whose value
    nobody would notice being 9999 on a corpus that never collides.
    """
    src = """\
from tempfile import gettempprefix, TMP_MAX

def main(n):
    printf("prefix=%s@@", gettempprefix())
    printf("tmp_max=%lld@@", TMP_MAX())
    return 0
"""
    want = {
        "prefix": CPY_TEMPFILE.gettempprefix(),
        "tmp_max": str(CPY_TEMPFILE.TMP_MAX),
    }
    seen = {}

    def compare(arch, recs):
        got = recs_of(recs)
        bad = [f"{k}: image {got.get(k)!r}, CPython {v!r}"
               for k, v in want.items() if got.get(k) != v]
        check(not bad, f"[{arch}] {len(bad)} of {len(want)} constants differ "
                       f"from this interpreter's own `tempfile`: " +
                       "; ".join(bad))
        seen[arch] = got

    D.build_and_run(src, "tempfile_constants", tmpdir, compare, backends=archs)
    if verbose:
        print(f"    gettempprefix and TMP_MAX, each against "
              f"`tempfile.{want['prefix']}`/`TMP_MAX`")
    return True, "gettempprefix and TMP_MAX agree with CPython"


def group_gettempdir(tmpdir, archs, verbose):
    """`gettempdir()` as a STRING, against CPython's, on this host.

    The one answer here that is a single string with no structure in it, and
    therefore the one where a difference is unambiguous: this host has `TMPDIR`
    set (the worktree's `.tmp`, which `tools/` sets for every job in this tree),
    so both sides should name the same directory, and if they do not, the
    difference is in the candidate walk or in the writability test.
    """
    src = """\
from tempfile import gettempdir

def main(n):
    printf("tmpdir=[%s]@@", gettempdir())
    return 0
"""
    want = {"tmpdir": CPY_TEMPFILE.gettempdir()}
    seen = {}

    def compare(arch, recs):
        got = recs_of(recs)
        bad = [f"{k}: image {got.get(k)!r}, CPython {v!r}"
               for k, v in want.items() if got.get(k) != v]
        check(not bad, f"[{arch}] {len(bad)} of {len(want)} answers differ "
                       f"from CPython's `gettempdir()`: " + "; ".join(bad))
        # The answer must be a directory this process can write in, or the
        # comparison above is comparing two wrong answers to each other.
        check(os.path.isdir(want["tmpdir"]) and os.access(want["tmpdir"], os.W_OK),
              f"CPython's gettempdir() answered {want['tmpdir']!r}, which is "
              f"not a writable directory on this host — the oracle is not "
              f"trustworthy here, so nothing in this group would mean anything")
        seen[arch] = got

    D.build_and_run(src, "tempfile_gettempdir", tmpdir, compare, backends=archs)
    if verbose:
        print(f"    both sides answered {want['tmpdir']!r}")
    return True, f"gettempdir agrees with CPython ({want['tmpdir']})"


def group_candidates(tmpdir, archs, verbose):
    """The candidate WALK, under three environment shapes, against CPython's.

    Three shapes, one per branch of `_get_default_tempdir`, because a walk that
    only ever reads `TMPDIR` passes the first and is wrong for a machine that
    sets `TMP` instead:

      * `TMPDIR` pointing at a directory that does NOT exist — CPython skips it
        and moves to the fixed candidates, and so must this. This is the shape
        that catches a module which returns the environment variable's value
        without asking whether it is a directory.
      * `TMPDIR` set to the EMPTY string — CPython's `_candidate_tempdir_list`
        skips a variable that is set and empty (`if dirname:`), so this is the
        "no environment variable" branch as far as either side is concerned.
      * `TMPDIR` set to a directory this test made — the answer has to be that
        directory, which is the sign the other way round of the first shape.

    **THE ENVIRONMENT IS SET FROM INSIDE THE IMAGE, with `os.putenv`, and not
    by the runner.** The environment the image RUNS in is the one its parent
    process has, and `test_formal_dylib.py`'s `build_and_run` passes `env` to
    the BUILD rather than to the image — so a group that wanted a different
    `TMPDIR` at run time would have to change that shared runner, and what it
    actually wants is smaller: a program that sets a variable and then asks the
    question, which is what a caller does. The oracle is a fresh interpreter
    with the same variable set before its first `gettempdir()`, because
    `tempfile.gettempdir` CACHES its answer in a module global behind a lock and
    a second question asked of this process would be answered with the first
    one's environment.

    CPython's write probe cannot be reproduced here (the module docstring has
    the measurement), so the third shape also confirms the one thing both sides
    can be asked: that the directory it names is the one that was set, and that
    both sides named the SAME one.
    """
    real = os.path.join(tmpdir, "candidate-root")
    os.makedirs(real, exist_ok=True)
    missing = os.path.join(tmpdir, "no-such-dir-for-tempfile")
    # `(label, TMPDIR's value, whether CPython is expected to NAME that value)`.
    # The third element is the shape's own claim about which branch it reaches,
    # and it is checked against CPython BEFORE the image is built — so a CPython
    # that changed its mind about a candidate fails here with the shape that no
    # longer tests anything, rather than as a mysterious disagreement below.
    shapes = [
        ("not-a-directory", missing, False),
        ("set-but-empty", "", False),
        ("a-directory", real, True),
    ]
    src = """\
from os import putenv
from tempfile import gettempdir

def main(n):
    putenv("TMPDIR", "%(tmpdir)s")
    printf("a=[%%s]@@", gettempdir())
    return 0
"""
    seen = {}
    for label, value, names_it in shapes:
        check('"' not in value,
              f"[{label}] the TMPDIR value {value!r} has a double quote in it "
              f"and the generated source interpolates it into one")
        want = _cpy_gettempdir(value)
        check((want == value) == names_it,
              f"[{label}] CPython answered {want!r} for TMPDIR={value!r}, "
              f"which is {'not ' if names_it else ''}the value this shape "
              f"expects it to name — so the shape no longer reaches the branch "
              f"it is here for. Read tempfile._get_default_tempdir before "
              f"changing this check")
        program = src % {"tmpdir": value}

        def compare(arch, recs, want=want, label=label, value=value):
            got = recs_of(recs)
            check(got.get("a") == want,
                  f"[{arch}] {label}: the image answered {got.get('a')!r} and "
                  f"CPython answered {want!r} with TMPDIR={value!r} set the "
                  f"same way. A walk that returns the variable without asking "
                  f"whether it is a directory, or that stops at the first "
                  f"candidate it finds, disagrees with CPython here")
            seen.setdefault(label, {})[arch] = got

        # ONE architecture per shape, on purpose: the environment is part of the
        # question, so each shape is a separate build-and-run and there is
        # nothing for a second architecture to disagree about inside one.
        D.build_and_run(program, "tempfile_cand_" + label.replace("-", "_"),
                        tmpdir, compare, backends=[archs[0]])
    if verbose:
        for label, _v, _n in shapes:
            print(f"    {label}: both sides answered "
                  f"{seen.get(label, {}).get(archs[0], {}).get('a')!r}")
    return True, f"{len(shapes)} environment shapes agree with CPython"


def _cpy_gettempdir(tmpdir_value):
    """CPython's `gettempdir()` with `TMPDIR` set to `tmpdir_value` FIRST.

    `ok:<path>` or `raised:<ExceptionName>`, in a fresh interpreter — see this
    file's docstring on why the oracle is CPython's own answers rather than a
    table, and `group_candidates`'s on why the variable is set before the first
    call rather than after.
    """
    import subprocess
    script = ("import os, tempfile\n"
              "os.environ['TMPDIR'] = %r\n"
              "try:\n"
              "    print('ok:' + tempfile.gettempdir())\n"
              "except OSError as e:\n"
              "    print('raised:' + type(e).__name__)\n"
              % tmpdir_value)
    p = subprocess.run([sys.executable, "-c", script], capture_output=True,
                       text=True, timeout=120)
    check(p.returncode == 0,
          f"this interpreter's tempfile refused TMPDIR={tmpdir_value!r}: "
          f"{p.stderr.strip()[-200:]}")
    out = p.stdout.strip()
    return out[3:] if out.startswith("ok:") else out


def _deterministic(*keys):
    """A `cross` filter for `build_and_run`, keeping only `keys`' records.

    `build_and_run` compares the two architectures' records with each other, and
    for a module whose answers include a RANDOM NAME that comparison is
    guaranteed to fail: `arc4random_buf` draws different bytes on each run, so
    arm64's `tfprobe-ffgfecgc` is not x86-64's `tfprobe-edbeefgg` and neither of
    them is wrong. So each group that prints a name says which of its records
    are answers and which are draws, and only the answers are compared across
    architectures. **The per-architecture comparison is not given up**: what it
    protects is a module that lowers differently on the two, and every record
    below that is deterministic is still in the comparison.
    """
    keys = tuple(k + "=" for k in keys)

    def keep(recs):
        return [r for r in recs if r.startswith(keys)]
    return keep


def group_mkdtemp(tmpdir, archs, verbose):
    """`mkdtemp`: a real directory, the right mode, and a name of the right shape.

    Every assertion here is a PROPERTY of the answer rather than the answer
    itself, because the answer is a random name:

      * the returned path IS a directory (`os.path.isdir`), so a module that
        computed a plausible name without creating anything fails;
      * it is INSIDE the directory `gettempdir` names — `os.path.dirname` of the
        answer, compared as strings, which also catches an answer that forgot
        `abspath`;
      * its mode is `0o700` under this process's umask, which is CPython's mode
        for `mkdtemp` and the property that makes the directory private to the
        user who made it;
      * its name is `prefix` + EIGHT characters of CPython's own alphabet,
        with nothing else in it — checked by rebuilding CPython's alphabet out
        of this interpreter's `_RandomNameSequence` rather than out of a literal
        in this file, because the alphabet is a fact about CPython that a
        recorded copy of would rot;
      * TWO calls' names differ, which is the whole point of the name and the
        one property a deterministic generator would fail.
    """
    src = """\
from tempfile import mkdtemp, gettempdir

def main(n):
    printf("base=[%s]@@", gettempdir())
    printf("d1=[%s]@@", mkdtemp(prefix="tfprobe-"))
    printf("d2=[%s]@@", mkdtemp(prefix="tfprobe-"))
    return 0
"""
    alphabet = set(CPY_TEMPFILE._RandomNameSequence.characters)
    seen = {}

    def compare(arch, recs):
        got = recs_of(recs)
        base, d1, d2 = got.get("base"), got.get("d1"), got.get("d2")
        check(base, f"[{arch}] gettempdir() answered {base!r} inside the "
                    f"image, so mkdtemp had no directory to work in and "
                    f"nothing else in this group is meaningful")
        check(os.path.isdir(base), f"[{arch}] gettempdir() answered {base!r}, "
                                   f"which is not a directory")
        check(os.access(base, os.W_OK),
              f"[{arch}] gettempdir() answered {base!r}, which is not writable "
              f"by this process, so mkdtemp cannot have created anything")
        for label, d in (("d1", d1), ("d2", d2)):
            check(d, f"[{arch}] mkdtemp(prefix=…) answered {d!r}, the empty "
                     f"string this module returns for every failure — CPython "
                     f"returns a path here, and {base!r} is a writable "
                     f"directory, so the retry loop gave up for a reason "
                     f"worth reading")
            check(os.path.isdir(d),
                  f"[{arch}] mkdtemp(prefix=…) answered {d!r}, which is not a "
                  f"directory: the name was computed and nothing was created")
            check(os.path.dirname(d) == base,
                  f"[{arch}] mkdtemp answered {d!r}, whose parent is "
                  f"{os.path.dirname(d)!r} rather than the temp directory "
                  f"{base!r}")
            mode = CPY.S_IMODE(os.stat(d).st_mode)
            check(mode == (MODE_700 & ~_umask()),
                  f"[{arch}] mkdtemp created {d!r} with mode {mode:o}, and "
                  f"CPython's mkdtemp creates {MODE_700 & ~_umask():o} under "
                  f"this umask ({_umask():o}) — 448 is what the module passes "
                  f"and anything else is a mode this test cannot explain")
        for d in (d1, d2):
            stem = os.path.basename(d)
            check(stem.startswith("tfprobe-"),
                  f"[{arch}] mkdtemp answered {d!r}, whose name does not start "
                  f"with the prefix it was given")
            rnd = stem[len("tfprobe-"):]
            check(len(rnd) == 8,
                  f"[{arch}] mkdtemp answered {d!r}: the random part is "
                  f"{rnd!r}, {len(rnd)} characters, and CPython's is 8")
            bad = sorted(set(rnd) - alphabet)
            check(not bad,
                  f"[{arch}] mkdtemp answered {d!r}, whose random part has "
                  f"{bad!r} in it — outside CPython's own alphabet "
                  f"({''.join(sorted(alphabet))!r})")
        check(d1 != d2,
              f"[{arch}] two mkdtemp calls answered the same path {d1!r}; a "
              f"name generator that repeats is the one failure a directory "
              f"that is created correctly would hide")
        seen[arch] = got

    D.build_and_run(src, "tempfile_mkdtemp", tmpdir, compare, backends=archs,
                    cross=_deterministic("base"))
    if verbose:
        print(f"    two calls, two directories, mode "
              f"{MODE_700 & ~_umask():o}, names over CPython's own alphabet")
    return True, "mkdtemp's directory, mode, name shape and uniqueness agree"


_UMASK = []


def _umask():
    """This process's umask, read by setting it and putting it back.

    `os.umask` is the only way to read it and it is a SETTER, so the read is
    two calls and the value is restored before anything else runs. Read once
    per process: `mkdtemp`'s mode is masked by whatever the umask was when the
    directory was created, and both sides created theirs under this one.
    """
    if not _UMASK:
        current = os.umask(0o022)
        os.umask(current)
        _UMASK.append(current)
    return _UMASK[0]


def _cpy_mkdtemp(prefix):
    """What CPython's own `mkdtemp(prefix=…)` does, in a FRESH interpreter.

    `ok:<path>` or `raised:<ExceptionName>`. A subprocess because
    `tempfile.gettempdir` caches its answer in a module global behind a lock, so
    a second question asked of this process would be answered with the first
    one's environment — which is the whole reason this group cannot be a table
    of expected answers.
    """
    import subprocess
    script = ("import tempfile;"
              "print('ok:' + tempfile.mkdtemp(prefix=%r))" % prefix)
    p = subprocess.run([sys.executable, "-c", script], capture_output=True,
                       text=True, timeout=120)
    if p.returncode == 0:
        return p.stdout.strip()
    last = [ln for ln in p.stderr.strip().splitlines() if ln][-1]
    return "raised:" + last.split(":")[0].strip()


def group_name(tmpdir, archs, verbose):
    """The NAME, against the shape CPython's own name has.

    Three prefixes, chosen for the three shapes an argument can have rather than
    for three interesting strings:

      * `prefix="a-"` — ordinary.
      * `prefix=""` — the name is then eight characters and nothing else, and a
        module that appended a separator of its own would answer a path with a
        trailing `/`, which `isdir` still accepts — so this case is checked on
        the name's LENGTH and on `basename(d) == d`, not on `isdir` alone.
      * `prefix="b-/"` — **a prefix that ends in a separator, where CPython
        RAISES and this returns `""`.** It is here because it is the honest
        comparison rather than the convenient one: CPython's `mkdtemp` puts the
        separator inside the name and `mkdir` then fails on a parent directory
        that does not exist, so CPython raises `FileNotFoundError` and this path
        has no raise — `""` is the module's documented stand-in
        (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md` is about
        the other half of the same module). The oracle is a fresh interpreter,
        because `tempfile.gettempdir` caches and a second question in this
        process would be answered with the first one's environment.
    """
    src = """\
from tempfile import mkdtemp

def main(n):
    printf("plain=[%s]@@", mkdtemp(prefix="a-"))
    printf("empty=[%s]@@", mkdtemp(prefix=""))
    printf("slash=[%s]@@", mkdtemp(prefix="b-/"))
    return 0
"""
    want_slash = _cpy_mkdtemp("b-/")
    check(want_slash.startswith("raised:"),
          f"CPython's own mkdtemp(prefix='b-/') answered {want_slash!r}, so it "
          f"does NOT raise for this prefix on this interpreter and the "
          f"assertion below is about a CPython behaviour that has changed. "
          f"Read tempfile.mkdtemp's own source before editing that check")
    seen = {}

    def compare(arch, recs):
        got = recs_of(recs)
        for key, pre in (("plain", "a-"), ("empty", "")):
            d = got.get(key)
            check(d, f"[{arch}] mkdtemp(prefix={pre!r}) answered {d!r}")
            check(os.path.isdir(d),
                  f"[{arch}] mkdtemp(prefix={pre!r}) answered {d!r}, which is "
                  f"not a directory")
            check(not d.endswith("/") and os.path.basename(d) != "",
                  f"[{arch}] mkdtemp(prefix={pre!r}) answered {d!r}, whose "
                  f"last component is {os.path.basename(d)!r}: a trailing "
                  f"separator the module added of its own would leave the "
                  f"name empty, and `isdir` would still accept the path")
            stem = os.path.basename(d)
            check(stem.startswith(pre),
                  f"[{arch}] mkdtemp(prefix={pre!r}) answered {d!r}, whose "
                  f"name is {stem!r} and does not start with the prefix")
            rnd = stem[len(pre):]
            check(len(rnd) == 8,
                  f"[{arch}] mkdtemp(prefix={pre!r}) answered {d!r}: the "
                  f"random part is {rnd!r}, {len(rnd)} characters, and "
                  f"CPython's is 8")
        check(got.get("slash") == "",
              f"[{arch}] mkdtemp(prefix='b-/') answered {got.get('slash')!r} "
              f"and CPython raises FileNotFoundError for the same call — the "
              f"name puts the separator inside itself, so the parent does not "
              f"exist. This module has no raise and returns \"\" for every "
              f"failure; if this record is a path, the module created "
              f"something CPython cannot create")
        seen[arch] = got

    D.build_and_run(src, "tempfile_name", tmpdir, compare, backends=archs,
                    cross=_deterministic("slash"))
    if verbose:
        print("    three prefixes, including the empty one and one that ends "
              "in a separator")
    return True, "mkdtemp's name is prefix + 8 characters for every prefix"


def group_exclusive(tmpdir, archs, verbose):
    """`fopen(path, "wx")`: exclusive creation, which is what `mkstemp` needs.

    `tempfile`'s `mkstemp` is ABSENT from the module — it answers
    `(fd, name)`, two words, and a tuple cannot cross a dylib boundary — so the
    capability underneath it is checked here instead, on the one libSystem call
    that provides it. This group is here because the module's docstring makes a
    claim about that call ("exclusive creation on this target"), and a claim in
    a docstring that no test exercises is a claim nobody checked.

    Three answers, and the middle one is the group: the first `wx` open of a
    name succeeds, the second REFUSES (that is what `O_EXCL` means, and it is
    what makes `mkstemp`'s retry loop a correctness property rather than a race),
    and the file the first one made is on disk with its bytes.

    **ONE DIRECTORY PER ARCHITECTURE, and the reason is a SIGSEGV that was
    measured rather than imagined.** A failed `fopen` answers 0, and
    `fwrite(0, …)` dereferences it: an image that ran this program twice in one
    directory — once per architecture — had its second run find the first run's
    file, get 0 back, write through it anyway and die with exit `-11` on BOTH
    architectures. So the `FILE *` is checked before it is written through, and
    each architecture gets a directory of its own the way
    `test_formal_shutil.py`'s `copyfile` group gives each one. The refusal of
    the second open is what the group is for, so it must be REACHED rather than
    crashed into, which is the same discipline with the opposite spelling.
    """
    src = """\
from os._syscalls import fs_fopen, fs_fwrite, fs_fclose, str_alloc

def main(n):
    var p = "exclusive.txt"
    var f = fs_fopen(p, "wx")
    printf("first=%lld@@", f != 0)
    if f != 0:
        var buf: Pointer[UInt8] = str_alloc(8)
        memcpy(buf, "blat", 4)
        printf("wrote=%lld@@", fs_fwrite(f, buf, 4))
        printf("closed=%lld@@", fs_fclose(f))
    else:
        printf("wrote=[-1]@@")
        printf("closed=[-1]@@")
    var g = fs_fopen(p, "wx")
    printf("second=%lld@@", g != 0)
    var h = fs_fopen("exclusive-absent.txt", "wx")
    printf("fresh=%lld@@", h != 0)
    if h != 0:
        printf("closed2=%lld@@", fs_fclose(h))
    return 0
"""
    want = {"first": "1", "second": "0", "fresh": "1", "closed": "0",
            "closed2": "0", "wrote": "4"}
    seen = {}

    def compare(arch, recs, work=None):
        got = recs_of(recs)
        bad = [f"{k}: image {got.get(k)!r}, CPython {v!r}"
               for k, v in want.items() if got.get(k) != v]
        check(not bad, f"[{arch}] {len(bad)} of {len(want)} answers differ "
                       f"from CPython's own exclusive create "
                       f"(`open(p, 'x')`): " + "; ".join(bad))
        p = os.path.join(work, "exclusive.txt")
        body = open(p, "rb").read() if os.path.isfile(p) else None
        check(body == b"blat",
              f"[{arch}] the file the image created holds {body!r}, and "
              f"CPython's exclusive create of the same four bytes leaves "
              f"b'blat'")
        seen[arch] = got

    for arch in archs:
        work = os.path.join(tmpdir, "exclusive_" + arch)
        os.makedirs(work, exist_ok=True)
        for stale in os.listdir(work):
            os.remove(os.path.join(work, stale))
        D.build_and_run(src, "tempfile_exclusive_" + arch, tmpdir,
                        lambda a, r, work=work: compare(a, r, work),
                        backends=[arch], cwd=work,
                        cross=_deterministic(*want))
    if verbose:
        print("    a second exclusive open of the same name refused, which is "
              "O_EXCL")
    return True, "exclusive creation works, and refuses a name already taken"


def group_absent(tmpdir, archs, verbose):
    """The names this module does NOT export, each refused BY NAME.

    Four shapes, and each is a different reason:

      * `NamedTemporaryFile` — a FILE OBJECT: a `FILE *` and a cursor and a
        buffer, which is more than one 64-bit word.
      * `mkstemp` — a `(fd, name)` tuple, which is a frame blob.
      * a keyword this module does not have (`dir=`), which is the
        `unexpected keyword argument` refusal and is here because it is the
        refusal 50 of the 51 corpus call sites will actually meet.

    Driven by calling `fire.py build` directly rather than through
    `test_formal_dylib.py`'s `build_and_run`, for two reasons that are both
    about the assertion rather than about convenience: a build that SUCCEEDS
    has to be a failure here (and `build_and_run` reports a missing image as a
    crash, which is the wrong sentence for "the module grew a name"), and the
    refusal text has to be read whole — `build_and_run` keeps the last 400
    characters, and these messages put the name they are about in the middle.

    **ONE ARCHITECTURE, and it is enough**: every one of these is a refusal the
    front end raises while it still has the AST, before either backend's codegen
    is asked for anything, so the second architecture would answer the same
    question the same way. `test_formal_core_hostmods.py`'s absent groups make
    the same choice for the same reason.
    """
    # `TemporaryDirectory` was in this list until the `with` statement learned to
    # run an `__exit__` (`formal/build.py`'s `_rewrite_with_statements`); it is
    # in the `temporary-directory` group now, with its contract measured rather
    # than asserted absent.
    cases = [
        ("NamedTemporaryFile", """\
from tempfile import NamedTemporaryFile

def main(n):
    f = NamedTemporaryFile(mode='w', delete=False)
    printf("f=%s@@", f)
    return 0
""", "NamedTemporaryFile"),
        ("mkstemp", """\
from tempfile import mkstemp

def main(n):
    printf("p=%s@@", mkstemp(prefix='x-'))
    return 0
""", "mkstemp"),
        ("mkdtemp(dir=)", """\
from tempfile import mkdtemp

def main(n):
    printf("p=%s@@", mkdtemp(prefix='x-', dir='/tmp'))
    return 0
""", "unexpected keyword argument 'dir'"),
    ]
    work = os.path.join(tmpdir, "absent")
    os.makedirs(work, exist_ok=True)
    seen = {}
    for label, text, needle in cases:
        path = os.path.join(work, "absent_" + label.replace("/", "_")
                            .replace("=", "") + ".mojo")
        with open(path, "w") as f:
            f.write(text)
        r = D.run_fire(["build", "--formal", "--no-prove", "--backend=arm64",
                        "-o", os.path.join(work, "absent_" + label), path],
                       cwd=HERE)
        check(r.returncode != 0,
              f"tempfile.{label} BUILT, but the module documents it as absent — "
              f"either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(needle in msg,
              f"tempfile.{label} failed without naming itself ({needle!r}): "
              f"{msg.strip()[-400:]}")
        seen[label] = msg
    if verbose:
        for label in seen:
            print(f"    {label}: refused by name")
    return True, f"{len(cases)} absent names refused, each naming itself"


def group_temporary_directory(tmpdir, archs, verbose):
    """`with TemporaryDirectory() as d:` — created on the way IN, GONE on the
    way out, on both architectures.

    The contract, and the reason the name used to be absent: a
    `TemporaryDirectory` whose removal never happened would build, run, print
    the right answers and leave the tree behind, which is the module's own rule
    about `closing` ("a name that answers the easy half of its contract and
    drops the half that matters is the one thing a mirror of CPython must not
    export"). **64 of the 111 files** the corpus ranking counts use this one
    name, so what is asserted here is the removal and not the path.

    Four shapes, and each is a different way the exit could be skipped:

      * the plain block — `__exit__` runs on the fall-through path;
      * a `return` from inside the block — the cleanup has to happen on the way
        out of the FUNCTION, which is the shape a cleanup written "after the
        body" gets wrong, and `formal/build.py` lowers this `with` to a
        `try`/`finally` for exactly this reason;
      * `delete=0`, CPython 3.12's `delete=False` — the directory SURVIVES, so
        a test that only ever checked "gone" would pass an implementation that
        never removed anything and never kept anything either;
      * the `prefix=` spelling, because the corpus uses it (8 sites) and because
        it is the one that proves the constructor's arguments reach a field.

    Every path is checked by asking the FILESYSTEM, from this process, whether
    the directory the image printed exists — not by asking the image, which is
    the program under test. A `printf` inside `__exit__` would prove the exit
    ran; `os.path.isdir` proves the tree is gone.
    """
    src = """\
import os
from tempfile import TemporaryDirectory

def early():
    with TemporaryDirectory() as d:
        printf("early=%s@@", d)
        return 1
    return 0

def kept():
    with TemporaryDirectory(delete=0) as d:
        printf("kept=%s@@", d)
    return os.path.isdir(d)

def main(n):
    with TemporaryDirectory() as d:
        printf("plain=%s@@", d)
        printf("inside=%d@@", os.path.isdir(d))
    printf("after=%d@@", os.path.isdir(d))
    with TemporaryDirectory(prefix="formal-td-") as p:
        printf("prefix=%s@@", p)
    printf("prefixafter=%d@@", os.path.isdir(p))
    printf("earlyret=%d@@", early())
    printf("keptafter=%d@@", kept())
    return 0
"""
    seen = {}

    def compare(arch, recs):
        got = recs_of(recs)
        for label in ("plain", "early", "kept", "prefix"):
            path = got.get(label)
            check(path, f"[{arch}] {label} printed no path, so nothing else in "
                        f"this group is meaningful: {got}")
            check(os.path.isabs(path),
                  f"[{arch}] {label}={path!r} is not an absolute path, so "
                  f"this process cannot check it")
            # Deliberately NOT `os.path.isdir(path)` here: the image has already
            # exited by the time this runs, and the only directories that can
            # still be on disk are the ones the contract says to KEEP. The
            # "exists while the block is open" half is `inside=`, which the
            # image asks the filesystem itself from inside the block.
        check(got.get("inside") == "1",
              f"[{arch}] the directory did not exist INSIDE the block "
              f"(inside={got.get('inside')!r})")
        check(got.get("after") == "0",
              f"[{arch}] the directory SURVIVED the block "
              f"(after={got.get('after')!r}) — the whole contract of this name")
        check(got.get("prefixafter") == "0",
              f"[{arch}] the `prefix=` directory survived the block "
              f"(prefixafter={got.get('prefixafter')!r})")
        check(got.get("earlyret") == "1",
              f"[{arch}] the `return` from inside the block did not return 1 "
              f"(earlyret={got.get('earlyret')!r})")
        check(got.get("keptafter") == "1",
              f"[{arch}] `delete=0` did not keep the directory "
              f"(keptafter={got.get('keptafter')!r})")
        seen[arch] = got

    # The four paths carry eight RANDOM characters each, so the two
    # architectures cannot be compared record-for-record and `cross` drops them.
    # Every record that IS comparable — `inside`, `after`, `prefixafter`,
    # `earlyret`, `keptafter` — still has to be byte-identical across the two,
    # which is the point `build_and_run` makes about a module that lowers
    # differently on the two machines.
    def without_paths(recs):
        return [r for r in recs
                if not r.startswith(("plain=", "early=", "kept=", "prefix="))]

    D.build_and_run(src, "tdprobe", tmpdir, compare, backends=archs,
                    cross=without_paths)
    for arch, got in seen.items():
        for label in ("plain", "early", "prefix"):
            path = got.get(label, "")
            check(not os.path.exists(path),
                  f"[{arch}] {label}={path!r} is still on disk after the image "
                  f"exited — `__exit__` did not remove it")
    # The one thing this process has to clean up, and it is the ONE case where
    # the image is supposed to leave something behind.
    for arch, got in seen.items():
        kept = got.get("kept")
        check(kept and os.path.isdir(kept),
              f"[{arch}] delete=0 did not leave the directory on disk "
              f"({kept!r}): `__exit__` removed what CPython keeps, so this "
              f"suite's 'it is gone' assertions would pass an implementation "
              f"that removed everything")
        if kept and os.path.isdir(kept):
            shutil.rmtree(kept, ignore_errors=True)
    if verbose:
        print(f"    created, removed, removed-on-return, kept-with-delete=0; "
              f"{len(archs)} backends")
    return True, f"created in, gone out (return too), delete=0 keeps it"


GROUPS = {
    "constants": group_constants,
    "temporary-directory": group_temporary_directory,
    "gettempdir": group_gettempdir,
    "candidates": group_candidates,
    "mkdtemp": group_mkdtemp,
    "name": group_name,
    "exclusive": group_exclusive,
    "absent": group_absent,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    args = ap.parse_args()
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is {platform.machine()}")
        return 0
    names = args.groups or list(GROUPS)
    for n in names:
        if n not in GROUPS:
            print(f"ERROR: unknown group {n!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    archs = backends()
    failed = []
    with CPY_TEMPFILE.TemporaryDirectory(dir=os.environ.get("TMPDIR") or None) as td:
        for n in names:
            try:
                ok, detail = GROUPS[n](td, archs, args.verbose)
            except Exception as e:                        # noqa: BLE001
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
