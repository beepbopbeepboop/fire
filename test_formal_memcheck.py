#!/usr/bin/env python3
r"""`tools/formal_memcheck.py`: the memory-safety instruments, and the fix they found.

    python3 test_formal_memcheck.py [-v] [group ...]

Groups: `units`, `harness`, `heap`, `fsfree`, `corpus`, `ledger`.  With no
argument, all of them.

WHAT IS BEING TESTED, AND WHY IT IS NOT A DUPLICATE OF ANYTHING
---------------------------------------------------------------
`test_formal_fuzz.py` and `test_formal_sweep.py` compare STDOUT AND EXIT CODE
against CPython.  That oracle is blind to a whole class of miscompile: an image
that reads past the end of an array, reads a local that was never assigned,
double-frees or leaks produces the right ANSWER, so no case in those files can
fail on it.  `tools/formal_memcheck.py` adds the four instruments that can see
it, and this file tests two different things about them:

  * that the INSTRUMENTS work -- a C program with a deliberate
    read-before-write, and a formal program with a deliberate one, must both be
    CAUGHT, and a program that reads nothing uninitialised must not be.  A
    memory-safety tool that has never fired on a known defect is a tool whose
    clean verdict means nothing, so the positive cases are half the file.
  * that the CLEAN BASELINE holds -- every row of `formal/memcheck/` on both
    architectures, with the verdict each row is documented to produce.  Those
    verdicts are not all MATCH and they are not all supposed to be: the corpus
    contains rows whose whole purpose is to report LEAK, to report CRASH, and
    to report a read of an uninitialised local, and a sweep that could not
    produce them would be a sweep whose instruments had stopped working.

Both architectures, x86-64 under Rosetta.  Every image is built with
`prove=False`: a memcheck sweep measures the IMAGE, and a Lean proof for each of
a few dozen programs is minutes this file has no use for.
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "tools")
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import formal_memcheck as M                                # noqa: E402

BACKENDS = ("arm64", "x86_64")
REC = "@@"
passed = failed = skipped = 0
VERBOSE = False


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print("PASS  " + name)
    else:
        failed += 1
        print("FAIL  " + name + ("  " + detail if detail else ""))


def skip(name, why):
    global skipped
    skipped += 1
    print("SKIP  %s  %s" % (name, why))


def host_machine():
    return platform.machine() in ("arm64", "aarch64")


def rosetta():
    """`True` when this host can also RUN an x86-64 image.

    The reason is printed rather than the skip being silent: a silent skip reads
    as a pass, and the x86-64 half of every row here is the half that cannot run
    anywhere but Apple silicon.
    """
    if host_machine():
        return True, ""
    return False, ("host is %s; an x86-64 image needs Rosetta 2, which only "
                   "Apple Silicon has" % platform.machine())


# ── units: the pieces, with no image ─────────────────────────────────────────

def test_units():
    """The parsers and the classifier, on text a reader can check by eye."""
    # macho_entry reads LC_MAIN's entryoff and the __TEXT vmaddr.  The two are
    # computed independently by the linker, which is exactly why this is a
    # function and not `linker.entry_offset()`: an image with globals in it
    # has a different entryoff and a different vmaddr, and a memcheck run that
    # guessed either would break the breakpoint on some layouts only.
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.out")
        M.build(os.path.join(HERE, "formal", "examples", "fact.mojo"), p,
                "arm64")
        got = M.macho_entry(p)
        check("macho_entry reads an entry address out of a real image",
              got is not None and got[0] > got[1],
              "got %r" % (got,))
        check("macho_entry says None on something that is not a Mach-O",
              M.macho_entry(os.path.join(HERE, "fire.py")) is None)
        with open(p, "wb") as f:
            f.write(b"not a mach-o" * 8)
        check("macho_entry survives a truncated file",
              M.macho_entry(p) is None)

    # `leaks --atExit` prints both shapes, and a parser that only knows one of
    # them reports "no leak report" on a clean image -- which is indistinguishable
    # from `leaks` having failed, i.e. from an instrument that is not running.
    for text, want in (
            ("Process 1234: 0 leaks for 0 total leaked bytes.", (0, 0)),
            ("Process 1234: 1 leak for 80 total leaked bytes.", (1, 80)),
            ("Process 1234: 64 leaks for 5120 total leaked bytes.", (64, 5120))):
        m = M.LEAK_RE.search(text)
        check("leaks line parsed: %r" % text[:40],
              m is not None and (int(m.group(1)), int(m.group(2))) == want,
              "got %r" % (m.groups() if m else None,))
    check("a line with no leak count is NOT a leak report",
          M.LEAK_RE.search("Process 1: 12 nodes malloced for 3 KB") is None)

    # `main`'s return value IS this path's exit status and it can be anything,
    # so a status of 246 is a program that answered 246 and not a process that
    # died.  Three shipped examples do exactly that.
    check("a large exit status is not a crash", not M._died(246))
    check("a large exit status is a life", M._lived(246))
    check("a negative status is a crash", M._died(-6))
    check("memcap's printed status is the one that keeps the sign",
          M.effective_status(250, "memcap: done, peak 0.0 GB across up to 1 "
                                 "procs (ceiling 2.0 GB), child exit -6") == -6)
    check("with no memcap line the status is the process's own",
          M.effective_status(129, "") == 129)

    # The lldb status line for a normal exit, and for a death.
    check("lldb's exit line is read",
          M._lldb_status("Process 1 exited with status = 20 (0x00000014)", "")
          == 20)
    check("lldb's stop line is not read as an exit code",
          M._lldb_status("* thread #1 stopped, stop reason: EXC_BAD_ACCESS", "")
          == "signal:EXC_BAD_ACCESS")

    # The harness is generated per backend and must name THAT backend's
    # registers.  `rbp` is the one that matters: poisoning it faults inside
    # dyld's exit path, after the program has printed the right answer, which
    # is a finding about dyld and not about the backend.
    with tempfile.TemporaryDirectory() as d:
        a = open(M.harness_path(d, "arm64")).read()
        x = open(M.harness_path(d, "x86_64")).read()
    check("the arm64 harness poisons the callee-saved set",
          "'x19'" in a and "'x28'" in a)
    check("the x86-64 harness does NOT poison rbp", "'rbp'" not in x)
    check("the x86-64 harness poisons rbx and r12-r15",
          "'rbx'" in x and "'r12'" in x and "'r15'" in x)
    check("both harnesses paint 8 MB below sp",
          "SPAN = %d" % M.POISON_SPAN in a and "SPAN = %d" % M.POISON_SPAN in x)
    check("the poison word is 0xA5A5A5A5A5A5A5A5",
          M.POISON_WORD == 0xA5A5A5A5A5A5A5A5)

    # `memcap` prints its BREACH line to stdout and then EXITS 0, because it is
    # reporting that it killed the child rather than failing itself.  A row that
    # decided "did it run away" from the exit status would call a killed child a
    # success, and this is the only shape the verdict has.
    check("a memcap BREACH line is recognised",
          M.BREACH_RE.search("memcap: BREACH  2.6 GB >  2.0 GB ceiling "
                             "(127%), 1 procs -- killing t") is not None)
    check("memcap's normal completion line is not a BREACH",
          M.BREACH_RE.search("memcap: done, peak 0.0 GB across up to 1 procs "
                             "(ceiling 2.0 GB), child exit 0") is None)


# ── harness: the instruments fire on a KNOWN defect ──────────────────────────

C_PROBE = r"""
#include <stdio.h>
static int f(void) { int x; return x; }
static int g(void) { int a[8]; int s = 0; for (int i = 0; i < 8; i++) s += a[i]; return s; }
int main(void) { printf("f=%d g=%d\n", f(), g()); return 0; }
"""
C_CLEAN = r"""
#include <stdio.h>
static int f(void) { int x = 7; return x; }
int main(void) { printf("f=%d\n", f()); return 0; }
"""


def _clang(src, arch, out):
    return subprocess.run(["clang", "-arch", arch, "-O0", "-o", out, src],
                          capture_output=True, text=True)


def test_harness():
    """The poison instrument, against C programs whose answer is known.

    This is the half of the file that makes a MATCH mean something.  A C
    program that reads an uninitialised local has to be CAUGHT by the paint,
    and a C program that does not has to be left alone; without both halves a
    clean verdict from `formal/memcheck/` is indistinguishable from a broken
    instrument.
    """
    if not host_machine():
        skip("the poison instrument fires on a known read-before-write",
             "host is %s, and the harness needs an Apple-Silicon lldb "
             "(LC_MAIN + Rosetta)" % platform.machine())
        return
    for arch in BACKENDS:
        ok, why = (True, "") if arch == "arm64" else rosetta()
        if not ok:
            skip("the poison instrument fires on a known read-before-write (%s)"
                 % arch, why)
            continue
        with tempfile.TemporaryDirectory() as d:
            dirty = os.path.join(d, "dirty")
            clean = os.path.join(d, "clean")
            p = os.path.join(d, "dirty.c")
            with open(p, "w") as f:
                f.write(C_PROBE)
            p2 = os.path.join(d, "clean.c")
            with open(p2, "w") as f:
                f.write(C_CLEAN)
            if _clang(p, arch, dirty).returncode or _clang(p2, arch, clean).returncode:
                skip("the poison instrument fires on a known read-before-write (%s)"
                     % arch, "clang could not build the probes")
                continue
            # `M.fixed_env()`, not `M.FIXED_ENV`: the child's `HOME` is a
            # private per-process directory and `FIXED_ENV` no longer carries
            # one, so building the env from the constant here would hand these
            # two probes the caller's real `$HOME` — the one thing the constant
            # exists to stop, and the reason the corpus rows do not share it.
            plain = M._run(M.run_argv(dirty, arch),
                           dict(os.environ, **M.fixed_env()),
                           M.RUN_TIMEOUT)["stdout"]
            pois = M.poison_of(dirty, arch, d, "cprobe")
            plain_clean = M._run(M.run_argv(clean, arch),
                                 dict(os.environ, **M.fixed_env()),
                                 M.RUN_TIMEOUT)["stdout"]
            pois_clean = M.poison_of(clean, arch, d, "cclean")
            check("the paint ran (%s)" % arch, pois["painted"],
                  "harness did not report a paint")
            if not pois["painted"] or not pois_clean["painted"]:
                continue
            check("the poison changes a read-before-write's answer (%s)" % arch,
                  pois["stdout"] != plain,
                  "plain %r poisoned %r" % (plain[:60], pois["stdout"][:60]))
            check("the poison leaves a program that initialises alone (%s)" % arch,
                  pois_clean["stdout"] == plain_clean,
                  "plain %r poisoned %r"
                  % (plain_clean[:60], pois_clean["stdout"][:60]))
            if VERBOSE:
                print("      plain   %s" % plain.strip())
                print("      poison  %s" % pois["stdout"].strip())


# ── heap: the formal path's only heap, and the fix ──────────────────────────

def _memcheck(program, backends=BACKENDS, workdir=None):
    """Run the tool over one program and return its rows."""
    with tempfile.TemporaryDirectory() as d:
        wd = workdir or os.path.join(d, "work")
        rows = []
        for backend in backends:
            rows.append(M.measure(os.path.basename(program), program, backend, wd))
        return rows


def test_heap():
    """`formal/memcheck/` on both backends, and the verdict each row documents."""
    if not host_machine():
        skip("the heap rows", "host is %s; a formal image needs Apple Silicon "
                              "or Rosetta" % platform.machine())
        return
    x86_ok, why = rosetta()
    backends = ("arm64", "x86_64") if x86_ok else ("arm64",)

    expect = {
        # name: (verdict that must appear, a sentence saying why)
        "blob_alloc_free.mojo": (
            "MATCH",
            "the clean heap case: allocate, write by subscript, append through "
            "the module's writer, read back, free -- and `fs_free` returns a "
            "defined 0 (see test_fsfree), so every instrument agrees"),
        "blob_overrun.mojo": (
            "MATCH",
            "a 4096-byte store past a 64-byte buffer does NOT fault: "
            "MallocGuardEdges guards a rounded-up region and a 64-byte request "
            "does not get one. The row is here so that 'no overrun detected' "
            "is never read as 'the backend is safe'"),
        "blob_alloc_leak.mojo": (
            "LEAK",
            "64 unfreed allocations: `leaks --atExit` must report 64 root "
            "leaks and 5120 bytes, and this is the row that proves the leak "
            "verdict still fires"),
        "blob_double_free.mojo": (
            "CRASH",
            "the malloc zone must notice the second `free`: SIGABRT, exit 134, "
            "on both architectures"),
        "blob_use_after_free.mojo": (
            "MATCH",
            "the row CLASSIFIES rather than prints: `freed_is_mine` is 0 under "
            "plain, under MallocScribble (0x55) and under the stack paint, and "
            "1 only if the byte still holds what the program stored"),
        "local_uninitialised.mojo": (
            "REFUSED",
            "`var a: Int` with no initialiser is a DECLARATION, not an "
            "assignment, so the read is a read of an undefined value and the "
            "build refuses it by name. Before 2026-10-05 it built, ran, exited "
            "0 and printed 1709223448 / 306062552 -- which the poison called "
            "NONDETERMINISTIC, and that is how it was found"),
        "list_subscript_past_end.mojo": (
            "MATCH",
            "`a[3]` on a three-element list does NOT read past the end: both "
            "emitters load the blob's own count, apply Python's negative-index "
            "rule and stop unless `count > index` unsigned, so the answer is "
            "stable and the row pins THAT. The message is asserted by "
            "test_formal_run.py's STDERR_CASES instead, and it cannot be "
            "asserted here: this sweep compares stdout and the exit status, "
            "which is exactly why the stop's silence went unnoticed -- it was "
            "a bare exit(1) on both architectures until 2026-10-05 and this "
            "row still reported MATCH throughout"),
        "stack_deep_recursion.mojo": (
            "MATCH",
            "40 frames of recursion, which arm64's 128 KB container budget per "
            "frame and an 8 MB stack afford"),
    }
    for name, (want, why) in sorted(expect.items()):
        path = os.path.join(HERE, "formal", "memcheck", name)
        rows = _memcheck(path, backends)
        for row in rows:
            if not row["built"]:
                skip("%s (%s)" % (name, row["backend"]),
                     "build refused: %s" % row["build_diagnostic"][:120])
                continue
            verdicts = row["verdicts"] or ["MATCH"]
            check("%s is %s (%s)" % (name, want, row["backend"]),
                  want in verdicts,
                  "got %s -- %s" % (",".join(verdicts),
                                    row["detail"].get("baseline", {}).get(
                                        "stdout", "")[:160]))
            if VERBOSE:
                print("      %-24s %s  %s" % (name, row["backend"],
                                             ",".join(verdicts)))

    # The leak row's NUMBERS, not just its verdict: a LEAK verdict from a
    # `leaks` invocation that reported something else would still be a LEAK.
    path = os.path.join(HERE, "formal", "memcheck", "blob_alloc_leak.mojo")
    row = _memcheck(path, backends)[0]
    if row["built"]:
        lk = row["detail"]["leaks"]
        check("the leak row reports 64 leaks of 5120 bytes",
              lk["ok"] and lk["leaks"] == 64 and lk["bytes"] == 5120,
              json.dumps(lk))


# ── fsfree: the undefined value the instruments found ───────────────────────

FS_FREE_UNDEF = """\
from os._syscalls import str_alloc, fs_free

# The reproducer for the defect `formal/memcheck.py`'s poison found in
# `os._syscalls.fs_free`, kept here as the regression test rather than only in
# the corpus: `free` is `void`, so `return free(p)` in a function declared
# `-> int` yielded whatever the previous call left in the return register.
# Measured before the fix, under the stack/register poison:
#     plain arm64 10485760   plain x86-64 2156285947
#     poison arm64 4194304   poison x86-64 2149996539
# and `platform_free` and `os_free` both `return fs_free(p)`, so they
# inherited it.
def main(n: Int) -> Int:
    # TWO buffers, not two frees of one: a second `free` of the same pointer is
    # a double free and the process aborts before the second line prints, which
    # is `formal/memcheck/blob_double_free.mojo`'s row and not this one's.  What
    # is under test is that TWO CALLS AGREE, and that needs two calls to reach.
    var a: Pointer[UInt8] = str_alloc(64)
    var b: Pointer[UInt8] = str_alloc(64)
    a[0] = 65
    b[0] = 66
    printf("free=%d\\n", fs_free(a))
    printf("free=%d\\n", fs_free(b))
    return 0
"""


def test_fsfree():
    """`fs_free` must return a DEFINED value, and say so identically twice.

    Run twice rather than compared against a golden number, because the whole
    defect was that the number was whatever happened to be in a register: a
    single-run comparison against 0 would have passed on the buggy version
    whenever the register happened to hold 0.
    """
    if not host_machine():
        skip("fs_free returns a defined value",
             "host is %s; a formal image needs Apple Silicon or Rosetta"
             % platform.machine())
        return
    backends = ("arm64", "x86_64") if rosetta()[0] else ("arm64",)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "fsfree_undef.mojo")
        with open(path, "w") as f:
            f.write(FS_FREE_UNDEF)
        for backend in backends:
            rows = _memcheck(path, (backend,), workdir=os.path.join(d, backend))
            row = rows[0]
            if not row["built"]:
                skip("fs_free returns a defined value (%s)" % backend,
                     "build refused: %s" % row["build_diagnostic"][:160])
                continue
            # A double free aborts, which is `blob_double_free`'s row and not
            # this one's: what matters here is that BOTH printed values are the
            # same and neither is 0xa5a5a5a5.
            out = row["detail"]["baseline"]["stdout"]
            values = [ln.split("=", 1)[1] for ln in out.strip().splitlines()
                      if ln.startswith("free=")]
            check("fs_free's value is defined and repeatable (%s)" % backend,
                  len(values) == 2 and values[0] == values[1]
                  and "a5a5a5a5" not in values[0],
                  "printed %r" % (values,))
            check("fs_free's value does not move under the poison (%s)" % backend,
                  row["detail"]["poison"]["painted"]
                  and row["detail"]["poison"]["stdout"] == out,
                  "plain %r poison %r"
                  % (out[:80], row["detail"]["poison"]["stdout"][:80]))
            if VERBOSE:
                print("      %-8s free printed %r" % (backend, values))

    # And the source says what it does, so a future edit that reintroduces
    # `return free(p)` is visible without running anything.
    src = open(os.path.join(HERE, "formal", "hostmods", "os",
                            "_syscalls.mojo")).read()
    # The body runs from `def fs_free(` to the next top-level `def`/`#` header,
    # not to a blank line: this function's docstring contains blank lines and
    # quotes the old body (`return free(p)`) in the prose that explains the
    # fix, so a blank-line split stops inside the docstring and a substring test
    # over the whole function would match the sentence rather than the code.
    tail = src.split("def fs_free(", 1)[1]
    body = re.split(r"\n(?=(?:def |# ))", tail, maxsplit=1)[0]
    code = re.sub(r'""".*?"""', "", body, flags=re.S)      # drop the docstring
    check("fs_free assigns the value it declares",
          "return 0" in code and "return free(" not in code,
          code[-200:])


# ── corpus and ledger ───────────────────────────────────────────────────────

def test_corpus():
    """Every shipped row builds for both backends, and the corpus is non-empty.

    A row that no longer builds is a hole in the coverage, and a hole that reads
    as a `REFUSED` line in a sweep output nobody reads.
    """
    if not host_machine():
        skip("the corpus rows build", "host is %s" % platform.machine())
        return
    # One row is DOCUMENTED to be refused, and the reason it is still in the
    # corpus is that a refusal which silently stops happening is the failure
    # this row exists to catch.  So "every row builds" is the wrong assertion
    # and "every row builds or refuses for its documented reason" is the right
    # one: a row that starts refusing for a NEW reason is a finding, and a row
    # that stops refusing is a finding.
    must_refuse = {"local_uninitialised.mojo"}
    rows = []
    for path in M.memcheck_sources():
        for backend in BACKENDS:
            out = os.path.join(tempfile.gettempdir(), "fm_%s.%s"
                               % (os.path.basename(path), backend))
            rc, why = M.build(path, out, backend)
            rows.append((os.path.basename(path), backend, rc, why))
            if os.path.exists(out):
                os.unlink(out)
    wrong = []
    for n, b, rc, w in rows:
        if rc and n not in must_refuse:
            wrong.append((n, b, w))
        if not rc and n in must_refuse:
            wrong.append((n, b, "it BUILDS: the declaration is counting as a "
                                "definition again, so the read is undefined"))
    check("every formal/memcheck row builds or refuses as documented",
          not wrong,
          "; ".join("%s/%s: %s" % (n, b, w[:110]) for n, b, w in wrong))
    for n in sorted(must_refuse):
        check("%s refuses on BOTH backends" % n,
              all(rc for nn, _b, rc, _w in rows if nn == n),
              "not refused on one of them")
    check("the corpus has a row per defect class",
          len(M.memcheck_sources()) >= 8,
          "%d rows" % len(M.memcheck_sources()))
    # `formal/examples` is the arithmetic half and must keep building too: a
    # memcheck sweep of the heap rows alone would not notice a regression in
    # everything else.
    ex = [p for p in M.example_sources()]
    check("the examples corpus is still there", len(ex) >= 50,
          "%d examples" % len(ex))


def test_ledger():
    """The committed ledger is well-formed and covers the corpus."""
    path = M.DEFAULT_LEDGER
    if not os.path.exists(path):
        skip("the ledger", "%s does not exist yet -- write it with "
                           "tools/formal_memcheck.py --write-ledger" % path)
        return
    payload = json.load(open(path))
    check("the ledger has a rows table", isinstance(payload.get("rows"), dict))
    rows = payload["rows"]
    # The check is a SET comparison in the SAME namespace the writer uses.  It
    # used to compare `len(rows)` against `len(memcheck_sources() +
    # example_sources()) * 2`, which is a count of full-path entries against a
    # count of `basename|backend` keys: the two can only ever agree by accident,
    # and a count cannot tell a program that lost its row from one that gained a
    # duplicate.  The writer keys on `basename|backend` (`ledger_key`), so this
    # builds the expected key set the same way and names what is missing.
    expected = {"%s|%s" % (os.path.basename(p), b)
                for p in M.memcheck_sources() + M.example_sources()
                for b in BACKENDS}
    missing = sorted(expected - set(rows))
    extra = sorted(set(rows) - expected)
    check("the ledger covers every corpus row on both backends",
          not missing,
          "no ledger row for: %s" % ", ".join(missing))
    check("the ledger has no row for a program the corpus no longer has",
          not extra,
          "ledger rows with no corpus program: %s" % ", ".join(extra))
    # Non-vacuous: dropping one row must be reported BY NAME.  This is the half a
    # length comparison cannot do, and it is what makes the check above a
    # coverage statement rather than a coincidence of two counts.
    if rows:
        sample = sorted(rows)[0]
        dropped = sorted(expected - (set(rows) - {sample}))
        check("the coverage check names a program whose ledger row is missing",
              dropped == [sample],
              "dropping %r reported %r" % (sample, dropped))
    check("every ledger row names a verdict",
          all(r.get("verdict") for r in rows.values()))
    # Every row whose name is one of the corpus's DOCUMENTED findings must say
    # so in the ledger, or the ledger is not the baseline it claims to be.
    documented = {"blob_alloc_leak.mojo": "LEAK",
                  "blob_double_free.mojo": "CRASH",
                  "local_uninitialised.mojo": "REFUSED"}
    wrong = [(k, r["verdict"]) for k, r in rows.items()
             if os.path.basename(k.split("|")[0]) in documented
             and r["verdict"] != documented[os.path.basename(k.split("|")[0])]]
    check("the ledger records the corpus's documented findings", not wrong,
          str(wrong[:4]))
    check("no ledger row carries an absolute path",
          not any(str(r.get("image", "")).startswith("/")
                  for r in rows.values()))


GROUPS = {
    "units": test_units,
    "harness": test_harness,
    "heap": test_heap,
    "fsfree": test_fsfree,
    "corpus": test_corpus,
    "ledger": test_ledger,
}


def main():
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", default=[])
    args = ap.parse_args()
    VERBOSE = args.verbose
    wanted = args.groups or list(GROUPS)
    for g in wanted:
        if g not in GROUPS:
            print("unknown group %r; groups are %s" % (g, ", ".join(GROUPS)))
            return 2
    for g in wanted:
        print("--- %s" % g)
        GROUPS[g]()
    print("Results: %d passed, %d failed, %d skipped"
          % (passed, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())