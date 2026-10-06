#!/usr/bin/env python3
r"""Build `formal/hostmods/stat.mojo` and RUN it, compared with CPython's `stat`.

    python3 test_formal_stat.py [-v] [group ...]

Groups: `consts`, `sweep`, `resolve`, `absent`. With no argument, all.

WHY AN ORACLE AND NOT A TABLE
-----------------------------
Every answer in the `sweep` group is a function of a mode integer, and nothing
in it is a fact about a filesystem. So the oracle is `stat.filemode` /
`stat.S_IS*` / `stat.S_IFMT` / `stat.S_IMODE` **in this process**, and a table
would be a second thing to be wrong: `filemode`'s table is seven rows of
"type bits to letter" times three permission rows with a setuid substitution
each, and a transcription of it is exactly the kind of thing that is right
about 0o100644 and wrong about 0o4644.

EXHAUSTIVE OVER THE WHOLE DOMAIN, WHICH IS THE POINT
------------------------------------------------------
`mode_t` is an unsigned short on this platform, so the corpus is **every one of
the 65,536 values a mode can take** — not a sample, and not a "representative"
subset — plus eleven values outside it.

`filemode` is a fourteen-row table over sixteen bits, `S_IFMT` is
`mode & 0o170000`, `S_IMODE` is `mode & 0o7777`, and each of the seven
predicates is one compare. Every one of those can be wrong for a set of modes a
sample would have had no obligation to include — the setuid-without-execute case
that prints `S` rather than `s`, the `S_IFSOCK` row that has to be tested
before `S_IFREG` because `S_IFSOCK == S_IFREG | S_IFDIR`, the `?` column for a
mode with no type bits at all — and on this target every one of them is
REACHABLE, so a sample is a decision to leave those cases untested.

The eleven out-of-range modes are the other half of the argument, and they are
why the module returns a STATUS rather than masking: CPython raises
`OverflowError` for all of them (measured, not quoted — see `OUT_OF_RANGE`),
and a module that masked instead would produce CPython's own answer for the low
sixteen bits and so agree with the oracle on modes the oracle rejects.

BOTH ARCHITECTURES, AND WHY
---------------------------
The module is pure integer and pointer work with no call into the C library
beyond `malloc`/`memset`/`memmove`, so it is the case where a two-architecture
divergence would be a pure lowering bug with nothing in the module to blame.
Every group is built and RUN for arm64 and for x86-64 and both answers are
compared against CPython. x86-64 runs under Rosetta 2 on Apple Silicon and is
SKIPPED (not failed) on a host with no x86-64 support, with the reason
printed. This is also the group that would catch `_filemode_cls` growing a
seventh parameter: SysV x86-64 passes six integer arguments in registers and
refuses a seventh (`FORMAL_x86_64_argument_registers`).
"""
import argparse
import os
import platform
import stat as CPY
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 300

REC = "@@"

# The record terminator, for the reason every hostmod test in this tree gives
# (`test_formal_dylib.py` states it): a separator this suite can read back
# without asking whether the image decoded a literal, `@@` being two bytes a
# real newline cannot collide with. So records go out back to back with a
# terminator of their own, and `filemode`'s output — ten characters of
# `-dlbcp?` and `rwxst` — cannot contain it.

# What CPython's own `stat` exports that this module must mirror, as NAMES.
# Read off the live module with `getattr`, so the oracle is the interpreter's
# value rather than a number typed here; the name is what is written down and
# the value is asked for.
CONSTANTS = [
    # permission bits
    "S_ISUID", "S_ISGID", "S_ISVTX",
    "S_IRUSR", "S_IWUSR", "S_IXUSR",
    "S_IRGRP", "S_IWGRP", "S_IXGRP",
    "S_IROTH", "S_IWOTH", "S_IXOTH",
    "S_IRWXU", "S_IRWXG", "S_IRWXO",
    "S_IREAD", "S_IWRITE", "S_IEXEC", "S_ENFMT",
    # file types
    "S_IFREG", "S_IFDIR", "S_IFLNK", "S_IFSOCK", "S_IFCHR", "S_IFBLK",
    "S_IFIFO", "S_IFWHT", "S_IFDOOR", "S_IFPORT",
    # os.stat_result indices
    "ST_MODE", "ST_INO", "ST_DEV", "ST_NLINK", "ST_UID", "ST_GID",
    "ST_SIZE", "ST_ATIME", "ST_MTIME", "ST_CTIME",
]

# The functions over a mode integer.
ACCESSORS = ["S_IFMT", "S_IMODE"]
PREDICATES = ["S_ISREG", "S_ISDIR", "S_ISLNK", "S_ISSOCK", "S_ISBLK",
              "S_ISCHR", "S_ISFIFO"]

# The type bits CPython's `_filemode_table` has a row for, plus the three this
# platform spells that produce `?`. Listed rather than walked: the sweep covers
# all 65,536 modes, which contains every one of them, so the only thing a
# separate walk would add is that the PLATFORM's number is the one CPython
# reports — and that is `group_consts`' job, name by name. Kept because a
# reader of this file needs to know the type column was not swept separately,
# and why.
TYPES = ["S_IFREG", "S_IFDIR", "S_IFLNK", "S_IFSOCK", "S_IFCHR", "S_IFBLK",
         "S_IFIFO", "S_IFWHT", "S_IFDOOR", "S_IFPORT"]

# Names CPython exports that this module deliberately does not, each with the
# reason the module's docstring gives. An omission that is not pinned is
# indistinguishable from an implementation.
ABSENT = [
    ("S_ISDOOR", "macOS has no door file type and CPython's predicate is "
                 "compiled out; answering 'no' would be a plausible wrong "
                 "answer on a platform that has them"),
    ("S_ISPORT", "as S_ISDOOR, for an event port"),
    ("S_ISWHT", "as S_ISDOOR, for a whiteout — the CONSTANT is here and the "
                "predicate is not"),
    ("ST_BIRTHTIME", "CPython 3.14's `stat` does not export it, so there is "
                     "no oracle for it even though Darwin's stat(2) has the "
                     "field"),
    ("ST_BLOCKS", "as ST_BIRTHTIME"),
    ("ST_BLKSIZE", "as ST_BIRTHTIME"),
    ("ST_FLAGS", "as ST_BIRTHTIME"),
    ("ST_RDEV", "as ST_BIRTHTIME"),
    ("ST_GEN", "as ST_BIRTHTIME"),
    ("ST_LSIZE", "as ST_BIRTHTIME"),
    ("ST_TYPE", "as ST_BIRTHTIME"),
    ("FILE_ATTRIBUTE_ARCHIVE", "a Windows attribute bit, on a platform whose "
                               "stat(2) has no such field"),
    ("FILE_ATTRIBUTE_READONLY", "as FILE_ATTRIBUTE_ARCHIVE"),
    ("FILE_ATTRIBUTE_HIDDEN", "as FILE_ATTRIBUTE_ARCHIVE"),
    ("FILE_ATTRIBUTE_SYSTEM", "as FILE_ATTRIBUTE_ARCHIVE"),
    ("FILE_ATTRIBUTE_DIRECTORY", "as FILE_ATTRIBUTE_ARCHIVE"),
]


# Modes OUTSIDE `mode_t`, where CPython raises and this module answers -1 (or
# `""` for `filemode`).  Measured on this tree's CPython 3.14: `stat.S_IFMT`,
# `stat.S_IMODE` and `stat.filemode` all raise `OverflowError("mode out of
# range")` for -1, 65536 and 0xFFFFFFFF, and 65535 is the largest mode any of
# them answers. So this list is the one place where the oracle is a RAISE, and
# `group_sweep` turns a raise into the module's documented status; if the module
# masked instead, every mode here would come back as CPython's answer for the
# low sixteen bits and the comparison would fail, which is the whole point.
# `0o170000` is deliberately NOT in this list, and that is the second thing the
# exhaustive sweep found on its first run: 0o170000 is 61440, which is INSIDE a
# `mode_t` and so is answered normally (`stat.filemode(0o170000)` is
# `'?---------'`). It looks like the mask's own value and reads as "clearly out
# of range", and a corpus assembled by reading `S_IFMT`'s constant rather than
# by asking `S_IFMT` would have put it here and compared the module's status
# against CPython's real answer.
OUT_OF_RANGE = [-70000, -65536, -1, 65536, 65537, 0o200000, 0o200001,
                0o1000000, 0x7FFFFFFF, 0xFFFFFFFF, 0x1234ABCD]


def want(m):
    """CPython's answer for one mode, as a list of eleven strings.

    `None` means "CPython raises", and the eleven strings are in the generated
    program's field order — `filemode`, `S_IFMT`, `S_IMODE`, then the seven
    predicates as `1`/`0`. Asking CPython here rather than reading a table is
    the reason this file can claim it is a mirror and not a second opinion.

    A raise is `None` and not an exception, because it is DATA for the out-of-
    range half of the corpus: `group_sweep` checks that the image's answer for
    those modes is the module's documented status and that CPython's own
    answer is indeed a raise. If CPython ever stops raising, this returns a
    value and the comparison becomes an ordinary one, which is the right way
    for that change to show up.
    """
    try:
        out = [CPY.filemode(m), CPY.S_IFMT(m), CPY.S_IMODE(m)]
        out += [1 if getattr(CPY, p)(m) else 0 for p in PREDICATES]
    except OverflowError:
        return None
    return [str(v) for v in out]


def corpus():
    """Every mode this group compares, and why each one is in it.

    TWO parts, and the first is the whole domain:

      1. **every one of the 65,536 values a `mode_t` can hold** — not a sample
         and not a "representative" subset. That is the entire argument of the
         module: `filemode` is a fourteen-row table over sixteen bits, its two
         masks are `& 0o170000` and `& 0o7777`, and the seven predicates are
         one compare each. Every one of those can be wrong for a set of modes
         no sample would be obliged to include, and on this target every one of
         them is REACHABLE, so the sweep is exhaustive. A sampled corpus over a
         table this size finds the bug that is in the sample.
      2. `OUT_OF_RANGE`, where CPython raises and the module answers -1.

    `TYPES` is no longer walked separately and no longer needs to be: 0..65535
    contains every type value the platform spells, because they are all inside
    sixteen bits. `S_IFDOOR` and `S_IFPORT` are 0, which is in the range too.
    The one thing an exhaustive sweep does NOT pin is the platform's own type
    bits, and those are pinned by `group_consts`, which reads each one out of
    CPython's `stat`.
    """
    return list(range(0, 65536)) + list(OUT_OF_RANGE)


def sweep_source():
    """The generated program, and the shape of its output.

    One record per mode:

        <mode>:<filemode>:<S_IFMT>:<S_IMODE>:<7 predicates>@@

    `filemode`'s ten characters are among `-dlbcp?rwxst`, none of which is a
    colon, so splitting the record on `:` is unambiguous — and it is checked
    rather than trusted: `group_sweep` below refuses a record that does not
    have exactly eleven fields, because a mis-aligned record would compare the
    wrong field against CPython and report a difference that is not one.

    FOUR `printf`s per record rather than one with eleven arguments. Not a
    style choice: the two backends build the C format string for a call out of
    what each operand statically is, and a call this wide is the shape where
    that is most likely to be wrong in a way no reader of this file would
    predict. Four calls of at most four arguments is a shape every other
    hostmod test in this tree already uses.

    THE CORPUS IS WALKED BY A LOOP RATHER THAN CARRIED IN A LIST, and that is
    a measured fact about the target rather than a preference. The first
    version built one function holding every mode as a list literal and the
    build was REFUSED on x86-64:

        s function has 16384 left for containers. A blob of 8-byte elements is
        [count][element...], so at most 2047 element(s) fit in what is left
        here — and the budget is shared with every other list, dict, string
        and receiver frame in the same body.

    A list literal is a frame blob, so a corpus carried as one is bounded by
    the frame budget — the same limit
    `“CODEGEN: a list literal longer than 4095 words dies on a bare AssertionError”` is about, from the
    other direction. So the 65,536 in-range modes are a `while` loop (which
    needs no table at all) and the eleven out-of-range ones are an eleven-word
    literal. The program then emits exactly the sequence `corpus()` returns, in
    the same order, which is what makes the two comparable without sharing an
    index.

    `record()` is a FUNCTION rather than inline text for one reason: 65,547
    copies of four `printf` calls is 262,188 call sites, and the point of the
    generated program is to compare 65,547 ANSWERS, not to stress the emitter's
    call-site budget. It also means the record shape is written once, so a
    change to it cannot desynchronise the program and the parser.
    """
    lines = [
        "import stat",
        "from stat import filemode, S_IFMT, S_IMODE",
        "from stat import S_ISREG, S_ISDIR, S_ISLNK, S_ISSOCK",
        "from stat import S_ISBLK, S_ISCHR, S_ISFIFO",
        "",
        "def record(m) -> int:",
        '    printf("%lld:%s:", m, filemode(m))',
        '    printf("%lld:%lld:", S_IFMT(m), S_IMODE(m))',
        '    printf("%lld:%lld:%lld:%lld:", S_ISREG(m), S_ISDIR(m), '
        'S_ISLNK(m), S_ISSOCK(m))',
        '    printf("%lld:%lld:%lld@@", S_ISBLK(m), S_ISCHR(m), S_ISFIFO(m))',
        "    return 0",
        "",
        "def in_range() -> int:",
        "    var m = 0",
        "    while m < 65536:",
        "        record(m)",
        "        m = m + 1",
        "    return 0",
        "",
        "def out_of_range() -> int:",
        "    var os_ = [%s]" % ", ".join(str(v) for v in OUT_OF_RANGE),
        "    for v in os_:",
        "        record(v)",
        "    return 0",
        "",
        "def main() -> int:",
        "    in_range()",
        "    out_of_range()",
        "    return 0",
    ]
    return "\n".join(lines) + "\n", corpus()


def consts_source():
    """Every constant, one call, no loop — so a failure names the name."""
    lines = ["import stat", "", "def main() -> int:"]
    for name in CONSTANTS:
        lines.append('    printf("%s=%%lld@@", stat.%s())' % (name, name))
    return "\n".join(lines) + "\n"


# ── build and run ───────────────────────────────────────────────────────────

def build(src, name, arch, tmpdir):
    path = os.path.join(tmpdir, name + ".mojo")
    with open(path, "w") as f:
        f.write(src)
    out = os.path.join(tmpdir, name + "." + arch)
    r = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         "--backend=" + arch, "-o", out, path],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    return r, out


def run(out, arch):
    argv = [out]
    if arch == "x86_64" and sys.platform == "darwin":
        argv = ["arch", "-x86_64", out]        # Rosetta 2
    r = subprocess.run(argv, capture_output=True, timeout=RUN_TIMEOUT, cwd=HERE)
    return r.returncode, r.stdout.decode("latin-1"), \
        r.stderr.decode("utf-8", "replace")


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


# ── the groups ──────────────────────────────────────────────────────────────

def group_consts(tmpdir, archs, verbose):
    """Every constant this module exports, against CPython's own value.

    One call per constant and no loop, so a wrong answer names the constant
    instead of an index, and `absent()` is not what catches a constant that
    was never written at all: a name the module does not have fails the BUILD
    here, which is a louder and more specific failure than a wrong number.
    """
    src = consts_source()
    for arch in archs:
        r, out = build(src, "stat_consts", arch, tmpdir)
        if r.returncode != 0:
            return False, f"[{arch}] build failed: " \
                          f"{(r.stderr or r.stdout).strip()[-400:]}"
        rc, so, se = run(out, arch)
        if rc != 0:
            return False, f"[{arch}] image exited {rc}: {se.strip()[:200]!r}"
        got = dict(rec.split("=", 1) for rec in so.split(REC) if rec)
        bad = []
        for name in CONSTANTS:
            want = str(getattr(CPY, name))
            if got.get(name) != want:
                bad.append(f"{name}: image {got.get(name)!r}, "
                           f"CPython {want!r}")
        check(not bad, f"[{arch}] {len(bad)} of {len(CONSTANTS)} constants "
                       f"differ from CPython:\n      " + "\n      ".join(bad))
        if verbose:
            print(f"    [{arch}] {len(CONSTANTS)} constants, each against "
                  f"CPython's own `stat`")
    return True, f"{len(CONSTANTS)} constants agree with CPython's stat"


def group_sweep(tmpdir, archs, verbose):
    """`filemode`, `S_IFMT`, `S_IMODE` and the seven predicates, exhaustively.

    The corpus is `corpus()` and it is not a sample; see that function for why
    the three parts are what they are. The comparison is per FIELD and per
    mode, and the first disagreement is reported with the mode written in
    OCTAL as well as decimal — a wrong mode is otherwise a five-digit decimal
    number with no way to tell a type-bit error from a permission-bit one.
    """
    src, modes = sweep_source()
    per_arch = {}
    for arch in archs:
        r, out = build(src, "stat_sweep", arch, tmpdir)
        if r.returncode != 0:
            return False, f"[{arch}] build failed: " \
                          f"{(r.stderr or r.stdout).strip()[-400:]}"
        rc, so, se = run(out, arch)
        if rc != 0:
            return False, f"[{arch}] image exited {rc}: {se.strip()[:200]!r}"
        recs = [rec for rec in so.split(REC) if rec]
        check(len(recs) == len(modes),
              f"[{arch}] the image reported {len(recs)} records for a corpus "
              f"of {len(modes)} — a program that printed fewer modes than it "
              f"walked is not a program whose answers can be compared")
        per_arch[arch] = recs

    for arch, recs in per_arch.items():
        bad = []
        raised = 0
        for m, rec in zip(modes, recs):
            fields = rec.split(":")
            check(len(fields) == 11,
                  f"[{arch}] record {rec!r} has {len(fields)} fields, not 11; "
                  f"a mis-aligned record compares the wrong field against "
                  f"CPython and reports a difference that is not one")
            got_mode = int(fields[0])
            check(got_mode == m,
                  f"[{arch}] record {rec!r} is for mode {got_mode}, and the "
                  f"corpus is walked in a fixed order the program and the "
                  f"oracle share — so one of them is wrong about the ORDER, "
                  f"which is a different bug from a wrong answer")
            got = fields[1:]
            expected = want(m)
            if expected is None:
                # CPython raises. The module documents a STATUS for this, and
                # the status is "" for `filemode` and -1 for everything else.
                raised += 1
                if got != [""] + ["-1"] * 9:
                    bad.append(f"mode {n(m)}: CPython raises OverflowError and "
                               f"the image says {got}, which is neither the "
                               f"module's documented status (an empty "
                               f"filemode and nine -1s) nor CPython's answer")
                continue
            if got != expected:
                bad.append(f"mode {n(m)}: image {got} != CPython {expected}")
        check(not bad,
              f"[{arch}] {len(bad)} of {len(modes)} modes differ from CPython; "
              f"first three:\n      " + "\n      ".join(bad[:3]))
        # Every out-of-range mode in the corpus must really be one CPython
        # rejects, or the count above is measuring nothing: a future CPython
        # that widened `mode_t` would silently stop testing the status.
        check(raised == len(OUT_OF_RANGE),
              f"[{arch}] {raised} of the {len(OUT_OF_RANGE)} out-of-range "
              f"modes raised OverflowError in CPython, so either the module "
              f"answered a status where CPython has an answer (and that "
              f"desynchronised the comparison above) or this tree's CPython no "
              f"longer rejects them")

    # Both architectures, against each other. The module is pure integer work
    # with no libc call past malloc/memset/memmove, so a disagreement here is
    # a lowering bug with nothing in `stat.mojo` to blame — which is the only
    # reason this group runs twice.
    if len(per_arch) == 2:
        a, b = archs
        diff = [(modes[i], per_arch[a][i], per_arch[b][i])
                for i in range(len(modes))
                if per_arch[a][i] != per_arch[b][i]]
        check(not diff,
              f"{len(diff)} of {len(modes)} modes differ between {a} and {b}; "
              f"the module is pure integer work, so a disagreement here is a "
              f"two-architecture lowering bug with nothing in stat.mojo to "
              f"blame. First three:\n      " +
              "\n      ".join(f"mode {n(m)}: {a} {x!r}, {b} {y!r}"
                              for m, x, y in diff[:3]))
    if verbose:
        print(f"    {len(modes)} modes x {len(per_arch)} architecture(s), "
              f"every field against CPython's own `stat`")
    return True, (f"all {len(modes)} modes agree with CPython on every field "
                  f"— the {len(OUT_OF_RANGE)} outside `mode_t` answering the "
                  f"documented status where CPython raises — on "
                  f"{' and '.join(archs)}")


def group_resolve(tmpdir, archs, verbose):
    """`stat` resolves where `formal/imports.py` says, and left the set.

    Both halves are load-bearing and for the same reason. The resolution
    assertion is what stops a module that exists but is not reachable from
    being counted as coverage; the `HOST_MODELLED` assertion is what stops a
    STALE ENTRY, which would refuse a file after the module that answers it is
    sitting in the tree — a false statement about the target rather than a
    conservative one, and the reason `resolve_module_path` consults the source
    tree first.
    """
    import formal.imports as I
    path = os.path.join(HERE, "formal", "hostmods", "stat.mojo")
    check(os.path.isfile(path), "no Mojo source for stat")
    got = I.resolve_module_path("stat")
    check(got is not None and os.path.samefile(got, path),
          f"import stat resolves to {got!r}, not {path!r}")
    check(I.host_module_tier("stat") == "",
          "stat is still in HOST_MODELLED; its Mojo source exists, so the "
          "entry is now a false statement about the target")
    check(I._is_host_module("stat") is False,
          "stat is still classified as a host module, which would make "
          "`import stat` refuse for a module that now has Mojo source")
    if verbose:
        print("    resolves into formal/hostmods/, out of HOST_MODELLED, "
              "out of the host-module union")
    return True, "stat resolves, and left both tiers"


def group_absent(tmpdir, archs, verbose):
    """Every name this module documents as absent, refused BY NAME.

    A CALL, not a bare name: a bare `stat.S_ISDOOR` is a read of a
    module-level name, which is refused for a different and vaguer reason and
    does not name the name being asked for.

    The needle is the name, so a module that grew one of these fails here by
    name — which is the point. An omission that is not pinned cannot be
    distinguished from an implementation by any reader of this file.
    """
    arch = archs[0]
    for name, _why in ABSENT:
        src = ("import stat\n\ndef main() -> int:\n"
               f"  stat.{name}(0)\n  return 0\n")
        r, _out = build(src, "stat_absent_" + name, arch, tmpdir)
        check(r.returncode != 0,
              f"stat.{name} resolved, but the module documents it as absent — "
              f"either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"stat.{name} failed without naming itself: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(ABSENT)} absent names refused, each naming itself")
    return True, f"{len(ABSENT)} absent names refused"


def n(m):
    """A mode in octal and decimal, because a five-digit decimal mode is
    unreadable and the whole point of reporting one is that a reader can see
    which bit class it is."""
    return f"{m} (0o{m:o})"


GROUPS = {
    "consts": group_consts,
    "sweep": group_sweep,
    "resolve": group_resolve,
    "absent": group_absent,
}


def x86_supported():
    """Whether this host can run an x86-64 image at all, and why not if it
    cannot. Rosetta 2 on Apple Silicon; anything else is skipped rather than
    failed, with the reason printed — the same rule
    `test_formal_os_backing.py` follows."""
    if platform.machine() in ("arm64", "aarch64"):
        return True, ""
    return False, f"host is {platform.machine()}; an x86-64 image needs " \
                  f"Rosetta 2, which only Apple Silicon has"


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
    for n_ in names:
        if n_ not in GROUPS:
            print(f"ERROR: unknown group {n_!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    ok86, why86 = x86_supported()
    archs = ["arm64"] + (["x86_64"] if ok86 else [])
    if not ok86:
        print(f"note: x86-64 half SKIPPED — {why86}")
    failed = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for name in names:
            try:
                ok, detail = GROUPS[name](tmpdir, archs, args.verbose)
            except Exception as e:
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            print(("PASS " if ok else "FAIL ") + name + (
                ("  " + detail) if detail else ""))
            if not ok:
                failed.append(name)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed "
          f"({', '.join(archs)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
