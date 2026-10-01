#!/usr/bin/env python3
"""WHICH refusal a file gets when a function contains BOTH an MLIR construct
and a name nothing places — the MLIR one, or whatever the name walk found
first.

What is under test. `formal/build.py`'s `check_module_symbols` refuses a
function by walking its body in SOURCE ORDER and raising on the first name it
cannot place, with one pre-pass in front of that walk for the refusals that
NAME A CONSTRUCT rather than a symptom. The dialect half of that pre-pass was
missing, so a bare `__mlir_op` — the spelling `std/sys/_assembly.mojo` builds
its entire body out of — was reached by the walk like any other name:

    $ cat b.mojo
    def main() -> Int32:
        var q = Unplaced                       # a genuinely unplaced name
        var v = __mlir_op.`pop.inline_asm`[    # the construct that is fatal
            _type=None, assembly="nop", constraints="",
        ]()
        print(v)

    $ python3 fire.py build --formal --no-prove b.mojo
    build: main: 'Unplaced' has no home: the module-level symbol table is
    empty for this unit, …

Reverse the two lines and the same file gets the useful message. Same
construct, same backend, same file's worth of source: the verdict was decided
by LINE ORDER. That is the defect this suite pins — and the second half of it
is that the pre-emption must not reach further than it claims to. An MLIR
construct this build ANSWERS (`a_target_query_is_not_pre_empted` below) is not
a construct it cannot lower, so pre-empting with the dialect text would refuse
a program that builds. The guard is the half that makes the fix honest.

MEASURED, over the population the defect applies to. Every stdlib file whose
OWN `check_module_symbols` verdict — its own body, with no import resolution in
front of it, which is what `formal_sweep.py` cannot show because it reports the
chain's terminal — used to name something other than MLIR: 6 files moved to the
MLIR refusal, 0 moved off it, and 0 changed verdict class, so nothing that
built started failing. They are `std/atomic/atomic.mojo`,
`std/builtin/globals.mojo`, `std/memory/unsafe.mojo`, `std/sys/_assembly.mojo`,
`std/sys/intrinsics.mojo`, `std/utils/numerics.mojo`. The doc is
`bugs/FORMAL_mlir_refusal_preemption.md`, which carries the full table and the
scope boundary this suite's cases were drawn from.

THE BOUNDARY, stated because it is a decision and not an accident: the
pre-emption is per FUNCTION. A construct that cannot be lowered at all
pre-empts every other name in the same function, because the file will not
build either way and the deeper limit is what the reader needs first; across
two functions each gets the most specific message available, because the
second function's refusal may be about something the first is not. Sixteen
stdlib files still have a verdict decided by the order of two FUNCTIONS — that
is the remainder, and it is in the doc.

Reverse-applied over the fix: 3 of the 7 cases fail, each of them naming the
wrong construct (`'Unplaced' has no home`), and none of them reporting a wrong
value. The other four are pins rather than reverse-apply failures and are
labelled as such where they are: the swapped-order pair's second case agreed
with the fix by source order already, the bare `__mlir_op` case had no
competing name to lose to, and both guards assert what the fix must NOT break.

Run:  python3 test_formal_mlir_precedence.py [-v] [case ...]
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 60


def build(src, out, backend):
    p = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         f"--backend={backend}", "-o", out, src],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


# (name, mojo source, needle, absent). Every one of these asserts the build
# FAILS with these words on BOTH backends. The needle is the reason the
# construct is refused, not a fixed phrase, so a rewording of the advice does
# not red the suite while a change of the verdict does. `absent`, where given,
# is a sentence the refusal must NOT contain — the assertion that decides which
# of two true refusals is the one the reader gets.
REFUSED = [
    # The defect, first shape: a missing local written ABOVE the construct.
    # Before, this was `'Unplaced' has no home`, which names a register table
    # and sends the reader to the allocator instead of to the construct the file
    # is actually about.
    ("a_missing_local_above_the_dialect_construct_does_not_win",
     "def main() -> Int32:\n"
     "    var q = Unplaced\n"
     "    var v = __mlir_op.`pop.inline_asm`[\n"
     "        _type=None, assembly=\"nop\", constraints=\"\",\n"
     "    ]()\n"
     "    print(v)\n"
     "    return 0\n",
     "is an MLIR dialect construct"),
    # The same program with the two statements SWAPPED. It is here because a
    # single case cannot tell "the pre-emption is gone" from "the pre-emption
    # happens to agree with source order": this pair can. Reverse-applied, only
    # the case ABOVE fails — this one agreed with the fix already, because
    # source order put the construct first — and a reader who wants to know
    # whether the fix changed anything is looking at the other three failures
    # (`an_attribute_template_keeps_its_own_refusal`,
    # `a_type_template_keeps_the_type_refusal`, and the first case) rather than
    # at this one.
    ("a_missing_local_below_the_dialect_construct_does_not_win",
     "def main() -> Int32:\n"
     "    var v = __mlir_op.`pop.inline_asm`[\n"
     "        _type=None, assembly=\"nop\", constraints=\"\",\n"
     "    ]()\n"
     "    var q = Unplaced\n"
     "    print(v)\n"
     "    return 0\n",
     "is an MLIR dialect construct"),
    # `__mlir_op` with no bracket at all, which is the spelling §2.2 of
    # bugs/FORMAL_known_limits.md measured building, linking and SEGFAULTING at
    # the first instruction, and which no suite case pinned. It is a limit, and
    # `test_formal_run.py`'s own note says what an unpinned limit is worth. It
    # passes reverse-applied too — nothing about it changed — which is the point
    # of a pin: it goes red when the limit is closed.
    ("a_bare_dialect_operation_is_refused_rather_than_built",
     "def main() -> Int32:\n"
     "    var n = 3\n"
     "    var a = __mlir_op.`pop.inline_asm`[n]\n"
     "    print(\"a = %llu\\n\", a)\n"
     "    return 0\n",
     "is an MLIR dialect construct"),
    # The pre-emption must not DOWNGRADE a more specific refusal to the generic
    # dialect text. This is the other half of the ordering rule: both constructs
    # name MLIR, and the bracketed one has a message about what a template is.
    # The unplaced name is first so that, before the fix, this reported the
    # name and the MLIR verdict never appeared at all.
    ("an_attribute_template_keeps_its_own_refusal",
     "def main(n: Int) -> Int:\n"
     "    var q = Unplaced\n"
     "    var t = __mlir_attr[`#kgen.simd<1> : !kgen.scalar<ui8>`]\n"
     "    return n\n",
     "assembles an MLIR attribute from a template"),
    # …and the same for the TYPE half, which `std/sys/info.mojo`'s `_TargetType`
    # is: a refusal that calls it an attribute is false about that binding, and
    # the word "type" is the only part of it a reader can act on.
    ("a_type_template_keeps_the_type_refusal",
     "def main(n: Int) -> Int:\n"
     "    var q = Unplaced\n"
     "    var t = __mlir_type[`!kgen.never`]\n"
     "    return n\n",
     "names an MLIR TYPE, not a value"),
    # The question this whole file turns on, asked of the OTHER side of the
    # rule. An ANSWERED target query sits beside a name nothing places; both
    # refusals would be true, and the verdict must be the placement one —
    # because the pre-emption is for constructs this path cannot lower, and this
    # one it lowers (see `a_target_query_is_not_pre_empted`, which is the same
    # query with the missing name removed). Before the fix this case reported
    # the missing name too, so it passes both before and after; it is here
    # because a fix that made the pre-emption unconditional would break it, and
    # a test that cannot tell those two apart is not a guard.
    ("a_answered_query_does_not_pre_empt_a_missing_local",
     "def main(n: Int) -> Int32:\n"
     "    var os_name = __mlir_attr[\n"
     "        `#kgen.param.expr<target_get_field,`,\n"
     "        __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`,\n"
     "        `, \"os\" : !kgen.string`, `> : !kgen.string`]\n"
     "    var q = Unplaced\n"
     "    print(\"os=\", os_name)\n"
     "    return 0\n",
     "'Unplaced' has no home", "is an MLIR dialect construct"),
]

# (name, source, expected stdout or None). The other guard, and it is a BUILD
# assertion: a `#kgen.param.expr<…>` target query is a QUESTION, this build
# answers it, and pre-empting it with the dialect refusal would refuse a
# construct `formal/model.py` answers everywhere else. `_fold_target_queries`
# has normally replaced the query with the literal it denotes before
# `check_module_symbols` runs, so this is also the case that pins that rewrite's
# coverage of a function body.
#
# The expected value is stated with its provenance rather than taken from an
# oracle, because CPython cannot parse `__mlir_attr`: `os` is `darwin` because
# the emitted container is a Mach-O image, which is a fact about the image and
# not about the machine that emitted it (`formal/model.py`'s `Target.__init__`
# derives it from `fmt` the same way). It is therefore the SAME on both
# architectures, which is why this case asserts one string for both.
GUARDED = [
    ("a_target_query_is_not_pre_empted",
     "def main() -> Int32:\n"
     "    var os_name = __mlir_attr[\n"
     "        `#kgen.param.expr<target_get_field,`,\n"
     "        __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`,\n"
     "        `, \"os\" : !kgen.string`, `> : !kgen.string`]\n"
     "    print(\"os=\", os_name)\n"
     "    return 0\n",
     "os= darwin\n"),
]


def run_refused(name, source, needle, absent, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        rc, text = build(src, os.path.join(tmpdir, f"{name}.{backend}"),
                         backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct with no "
                           f"answer (expected a refusal naming {needle!r}); "
                           f"the binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-220:]}")
        if absent is not None and absent in text:
            return False, (f"--backend={backend} refused with {absent!r}, "
                           f"which is the pre-emption this case says must not "
                           f"happen here: {text.strip()[-220:]}")
    if verbose:
        print(f"      refused identically on arm64 and x86-64: {needle!r}")
    return True, ""


def run_guarded(name, source, want_stdout, tmpdir, verbose):
    """Both architectures must BUILD, and on this one the image must RUN.

    arm64 only for the execution, for the reason `test_formal_comptime_string.py`
    gives: a formal x86-64 Mach-O needs Rosetta to launch on an arm64 Mac. The
    build half is what this case is really about, so it is checked on both.
    """
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(src, out, backend)
        if rc != 0:
            return False, (f"--backend={backend} refused a construct this build "
                           f"answers: {text.strip()[-220:]}")
        if not os.path.isfile(out):
            return False, f"--backend={backend} reported success, no binary"
        if backend != "arm64" or want_stdout is None:
            continue
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        if run.stdout != want_stdout:
            return False, (f"stdout {run.stdout!r} != {want_stdout!r} — a wrong "
                           f"value is the worse outcome, not a refusal")
        if run.returncode != 0:
            return False, f"exit status {run.returncode}, expected 0"
    if verbose:
        print(f"      built on both architectures"
              + (f" and printed {want_stdout!r}" if want_stdout else ""))
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    known = {c[0] for c in REFUSED} | {c[0] for c in GUARDED}
    if args.cases:
        missing = set(args.cases) - known
        if missing:
            print(f"ERROR: unknown case(s): {sorted(missing)}",
                  file=sys.stderr)
            return 2

    checks = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for entry in REFUSED:
            name, source, needle = entry[0], entry[1], entry[2]
            absent = entry[3] if len(entry) > 3 else None
            if args.cases and name not in args.cases:
                continue
            try:
                checks.append((name,) + run_refused(name, source, needle,
                                                    absent, tmpdir,
                                                    args.verbose))
            except subprocess.TimeoutExpired:
                checks.append((name, False, "timed out"))
        for name, source, want_out in GUARDED:
            if args.cases and name not in args.cases:
                continue
            try:
                checks.append((name,) + run_guarded(name, source, want_out,
                                                    tmpdir, args.verbose))
            except subprocess.TimeoutExpired:
                checks.append((name, False, "timed out"))

    passed = failed = 0
    for name, ok, detail in checks:
        if ok:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed += 1
            print(f"  FAIL  {name}: {detail}")

    print(f"\nMLIR refusal precedence: PASS={passed} FAIL={failed}")
    if platform.machine() not in ("arm64", "aarch64"):
        print("NOTE: the arm64 execution half was skipped — this host is "
              f"{platform.machine()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())