#!/usr/bin/env python3
"""MEMORY SAFETY of the executables the formal backend builds.

    python3 tools/formal_memcheck.py --backends arm64,x86_64 --jobs 8
    python3 tools/formal_memcheck.py --fuzz 200 --seed memcheck
    python3 tools/formal_memcheck.py --program formal/examples/subscript_var.mojo

WHY THIS EXISTS
---------------
`tools/formal_fuzz.py` and `tools/formal_sweep.py` compare STDOUT AND EXIT
CODE against CPython.  That is a semantic oracle and it is blind to a whole
class: a program whose OUTPUT happens to be right can still read past the end
of an array, read a local that was never assigned, double-free, or leak.  None
of those change the answer the corpus compares, so none of them are bugs the
corpus can find.  This tool runs the same images under the four instruments
that DO see them, on both backends, and reports the difference.

WHAT IS MEASURED, PER IMAGE
---------------------------
  baseline       the plain run: stdout + exit status, TWICE.  Two runs that
                 disagree are a finding in their own right (`NONDETERMINISTIC`)
                 because the only source of run-to-run variation in a
                 straight-line program is state nobody wrote.
  malloc-debug   the plain run with macOS's own malloc instrumentation —
                 `MallocGuardEdges` puts a guard page on the far side of every
                 large block so an overrun faults instead of corrupting a
                 neighbour, `MallocScribble` fills freed memory with 0x55 so a
                 use-after-free reads a recognisable pattern, and
                 `MallocPreScribble` fills fresh blocks with 0xAA so an
                 uninitialised heap read reads 0xaaaa....
  leaks          `leaks --atExit`, parsed for the leak count and bytes.  The
                 baseline for "should be zero" is the same measurement on the
                 same image, not a constant: libSystem's own allocations
                 settle at 0 leaks for every well-behaved image (measured),
                 so a non-zero count is the program's.
  poison         the stack below sp, plus the registers the ABI allows a
                 function to read only after writing, are overwritten with
                 0xA5A5... at the image's entry point, and the program then
                 runs.  Output that DIFFERS from the baseline is reading
                 memory that holds no value.  This is the check the differential
                 corpus structurally cannot make.

VERDICTS
--------
  MATCH             every instrument agrees with the baseline.
  NONDETERMINISTIC  two baseline runs disagree.  Uninitialised read.
  POISON-DIVERGES   output under poison differs from the baseline.
  POISON-CRASH      died under poison (signal, or non-zero where the baseline
                    was zero).
  SCRIBBLE-DIVERGES output under malloc-debug differs from the baseline.
  SCRIBBLE-CRASH    died under malloc-debug.
  LEAK              `leaks --atExit` reported a non-zero leak count.
  CRASH             the baseline run itself died.  Reported, and NOT counted
                    as a memcheck finding: a program that crashes before any
                    instrument is on it is a correctness bug the differential
                    corpus owns.

THE POISON HARNESS, AND WHY IT IS AN lldb SCRIPT
-------------------------------------------------
The paint has to happen in the last instant before the program's own frames
exist, and nothing can be scheduled that late from inside the process.  The
obvious instrument — a `DYLD_INSERT_LIBRARIES` dylib whose constructor paints
— does not work, and the reason is worth recording because it cost an hour:

  * A constructor runs during dyld's initialisation pass.  The rest of
    libSystem's startup then consumes a few hundred KB of exactly the stack
    that was painted, and by the time `main` runs the pattern is gone.
    Measured: reading an uninitialised array at main's entry gives byte-identical
    results with and without the constructor, and never 0xA5.
  * A dylib that DEFINES `main` and forwards via `RTLD_NEXT` is not called at
    all: dyld reaches the entry point through `LC_MAIN`'s `entryoff`, not
    through a symbol lookup, so there is no interposition to take.  Measured:
    the interposer's log file is never created.
  * A constructor that paints, plus a constructor-order trick, is the same
    constructor.

So the paint is done from outside, at a breakpoint on the image's own entry
address (read out of `LC_MAIN`, plus the `__TEXT` vmaddr).  That is exactly the
instruction before which the program's first frame does not exist, and it is
also the only place from which the callee-saved registers can be written at
all — see `POISON_REGISTERS`.

POISON_REGISTERS is per architecture and the difference is not cosmetic:

  * arm64 AAPCS64: the formal backend puts a function's locals in the
    callee-saved registers x19-x28 as readily as on the stack, so an
    uninitialised local in a register is invisible to a stack-only paint.
    Measured: a program printing two never-assigned `var`s reads its uninitialised
    value from x20, and the value printed is unchanged by a stack-only paint.
    Poisoning x19-x28 as well makes it print 0xa5a5a5a5a5a5a5a5 + 10.
  * x86-64 SysV: `rbp` MUST NOT be poisoned.  Measured: poisoning rbp makes the
    process fault inside `dyld` after the program's own code has finished and
    printed the right answer, at `movq -0xf8(%rbp), %rax` — dyld's exit path
    reads a frame slot relative to a frame pointer the program's entry stub
    never established.  `rbx` and `r12`-`r15` are safe to poison (measured), so
    they are, along with the caller-saved temporaries: the x86-64 formal
    codegen keeps its locals in the frame (`subq $0x4110, %rsp`) so the stack
    paint is what finds them, and the register poison is there for the shapes
    that spill.

WHERE THE STATE GOES
--------------------
  --workdir     build/formal_memcheck   images, the generated lldb harness,
                                        and the per-run logs.  git-ignored.
  --ledger      tools/formal_memcheck_ledger.json, written with `--write-ledger`.

The ledger is the clean BASELINE: one row per (program, backend) carrying the
baseline stdout digest, exit status, leak count and verdict.  A later run that
sees a different verdict for a row is reported as DRIFT, so a sweep over a few
hundred programs is readable and a regression in the corpus is visible without
diffing a thousand rows by hand.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_WORKDIR = os.path.join(HERE, "build", "formal_memcheck")
DEFAULT_LEDGER = os.path.join(HERE, "tools", "formal_memcheck_ledger.json")

RUN_TIMEOUT = 30
BUILD_TIMEOUT = 180
LDB_TIMEOUT = 120
LEAKS_TIMEOUT = 120

BACKENDS = ("arm64", "x86_64")

#: A fixed environment for every run.  A program that reads the environment
#: reads the PROCESS, so an inherited block would make a verdict depend on the
#: shell that started the sweep.  Same reasoning as `formal_fuzz.FIXED_ENV`.
#:
#: **`HOME` is a value, not a scratch directory, and it must still not be a
#: SHARED one.**  It was the literal `"/tmp"`, which is wrong for a reason that
#: has nothing to do with scratch: every image this tool runs gets the SAME
#: `HOME`, so two concurrent sweeps — or a sweep and anything else on the box —
#: have their children writing into one directory, and a program that creates a
#: file under `$HOME` produces a verdict that depends on which run got there
#: first.  That is the same hazard `formal/lean.py::scratch_dir`'s docstring
#: records for generated `.lean` files (`tu_grind.py`'s shared
#: `os.environ.get('CLAUDE_JOB_DIR', '/tmp')`), one level up: `scratch_dir` says
#: a NAMED path is the bug and `mkdtemp` is the fix, and a child's `HOME` is a
#: named path.  `test_formal_sweep_truth.py::TestScratchDirEstate` caught the
#: literal, and it is right to: `ast` cannot see that this one is an environment
#: value, so the fix is to make it true rather than to exempt it.
#:
#: It is resolved per CALL by `fixed_env()` rather than spelled here, because a
#: per-RUN directory does not exist at import time and a per-MODULE one would be
#: shared by exactly the concurrent runs this is fixing.
_HOME_DIR: str | None = None


def fixed_env() -> dict:
    """`FIXED_ENV` with a PRIVATE `HOME`, created once per process.

    `tempfile.mkdtemp` rather than a name under `build/`, for the reason
    `scratch_dir` gives: the run is what makes it unique, and a named path is
    what two runs collide on.  Not removed at exit — a child's `HOME` outliving
    the sweep is a directory in `TMPDIR`, which is the system sweeper's job and
    not this tool's, and removing it while a child is still reading it would be
    worse than leaving it.
    """
    global _HOME_DIR
    if _HOME_DIR is None:
        import tempfile
        _HOME_DIR = tempfile.mkdtemp(prefix="formal-memcheck-home.")
    env = dict(FIXED_ENV)
    env["HOME"] = _HOME_DIR
    return env


FIXED_ENV = {
    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    "LANG": "C",
    "LC_ALL": "C",
    "TERM": "dumb",
}

#: macOS's own malloc instrumentation.  `MallocErrorAbort` turns a detected
#: corruption into an abort instead of a warning line, so a heap bug is a
#: SCRIBBLE-CRASH rather than a silent wrong answer.
MALLOC_DEBUG = {
    "MallocGuardEdges": "1",
    "MallocScribble": "1",
    "MallocPreScribble": "1",
    "MallocCheckHeapStart": "1",
    "MallocCheckHeapEnd": "1",
    "MallocErrorAbort": "1",
}

POISON_BYTE = 0xA5
POISON_WORD = 0xA5A5A5A5A5A5A5A5
#: 8 MB.  The main thread's stack is 8 MB on this host and a formal program's
#: whole recursion budget is inside it, so painting the whole mapped region
#: below sp is what makes the paint cover the DEEPEST frame and not just the
#: first few.
POISON_SPAN = 8 * 1024 * 1024

POISON_REGISTERS = {
    # AAPCS64: x9-x15 are the caller-saved temporaries, x19-x28 the
    # callee-saved set a local can be allocated to.
    "arm64": ["x%d" % i for i in range(9, 16)] + ["x%d" % i for i in range(19, 29)],
    # SysV: rbp is deliberately ABSENT -- see the module docstring.
    "x86_64": ["rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11",
               "rbx", "r12", "r13", "r14", "r15"],
}

HARNESS = '''\
# GENERATED by tools/formal_memcheck.py -- do not edit; regenerate instead.
#
# Runs inside lldb at a breakpoint on the image's own entry address: paints
# every mapped page of the stack below sp, then writes the poison word into
# the registers the ABI allows a function to read only after writing.
import lldb

SPAN = %(span)d
WORD = %(word)d
NAMES = %(names)r

proc = lldb.debugger.GetSelectedTarget().GetProcess()
frame = proc.GetSelectedThread().GetSelectedFrame()
sp = int(frame.GetSP())
err = lldb.SBError()
wrote = proc.WriteMemory(sp - SPAN, b"\\xa5" * SPAN, err)
if not err.Success():
    print("MEMCHECK-PAINT-FAILED %%s" %% err)
for name in NAMES:
    frame.FindRegister(name).SetValueFromCString(hex(WORD))
print("MEMCHECK-PAINT sp=%%#x wrote=%%d" %% (sp, wrote))
'''


# ── the image ───────────────────────────────────────────────────────────────

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
LC_MAIN = 0x80000028


def macho_entry(path: str):
    """The vmaddr of an executable's entry point, or None.

    Read out of the image rather than taken from `formal/macho_linker.py`'s
    constants: the memcheck tool has to work on any formal-built Mach-O, and
    the four entry layouts (with/without externs, with/without globals) are
    exactly the thing that varies.  Also the only way to get an address an
    lldb breakpoint can be placed on for an image with no symbol table, which
    every formal image is.

    Returns `(entry_vmaddr, text_vmaddr)`: the second is the slide base lldb
    reports, kept so the caller can log an address it can reproduce by hand.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if len(data) < 32 or struct.unpack_from("<I", data, 0)[0] != MH_MAGIC_64:
        return None
    ncmds = struct.unpack_from("<I", data, 16)[0]
    off = 32
    entryoff = None
    text = None
    for _ in range(ncmds):
        if off + 8 > len(data):
            return None
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmdsize < 8:
            return None
        if cmd == LC_SEGMENT_64 and data[off + 8:off + 24].rstrip(b"\0") == b"__TEXT":
            text = struct.unpack_from("<Q", data, off + 24)[0]
        elif cmd == LC_MAIN:
            entryoff = struct.unpack_from("<Q", data, off + 8)[0]
        off += cmdsize
    if entryoff is None or text is None:
        return None
    return text + entryoff, text


def run_argv(path: str, backend: str, tool: str = None) -> list:
    """How to execute `path` on this host, and how to execute a TOOL on it.

    An x86-64 image on Apple silicon needs Rosetta 2, which is what
    `arch -x86_64` asks the kernel for.  `tool` is there because `leaks` has to
    run AS the target architecture too: measured, `leaks --atExit -- arch
    -x86_64 <an x86-64 image>` reports NOTHING at all (the wrapper `exec`s the
    image and `leaks` loses it), while `arch -x86_64 leaks --atExit -- <image>`
    reports the leak count.  So the `arch` prefix goes in front of the TOOL,
    not in front of the image.
    """
    prefix = []
    if backend == "x86_64" and sys.platform == "darwin" and _is_apple_silicon():
        prefix = ["arch", "-x86_64"]
    if tool:
        return prefix + [tool, "--atExit", "--", path]
    return prefix + [path]


def _is_apple_silicon() -> bool:
    import platform
    return platform.machine() in ("arm64", "aarch64")


# ── building ────────────────────────────────────────────────────────────────

#: The one-image builder, as source.  It is a SEPARATE PROCESS on purpose:
#: `formal.build` is a 20k-line module with module-level caches, so a sweep that
#: called `compile_formal` from eight threads made concurrent calls into
#: compiler state whose thread-safety nothing asserts.  Measured 2026-10-05: one
#: sweep of the `containers` mix came back with 37 x86-64 images REFUSED with
#: `the image would bind 1 symbol(s) that nothing provides ...: write`, an
#: audit failure that is about the LINK LINE and cannot be a property of the
#: program; three later sweeps of the same mix were clean, so it was not
#: reproducible -- which is exactly why it is worth not doing.  A subprocess
#: per image removes the question, and also stops one compiler crash from
#: taking the sweep with it.
BUILD_ONE = (
    "import sys\n"
    "sys.path.insert(0, %r)\n"
    "from formal.build import compile_formal\n"
    "try:\n"
    "    compile_formal(sys.argv[1], output=sys.argv[2], prove=False,\n"
    "                check=False, arch=sys.argv[3])\n"
    "except Exception as e:\n"
    "    sys.stderr.write('%%s: %%s' %% (type(e).__name__, e))\n"
    "    raise SystemExit(1)\n"
)


def build(source: str, out: str, backend: str):
    """Compile `source` for `backend` with no proof. (rc, diagnostic)

    `prove=False` and `check=False` because a memcheck sweep measures the
    IMAGE, and generating and checking a Lean proof for each of a few hundred
    programs is minutes of Lean this tool has no use for.  The proof path is
    `tools/suite.py`'s business.
    """
    env = dict(os.environ)
    env.update(fixed_env())
    env["PYTHONPATH"] = HERE
    argv = [sys.executable, "-c", BUILD_ONE % HERE, source, out, backend]
    r = _run(argv, env, BUILD_TIMEOUT)
    if r["rc"] == 0 and os.path.exists(out):
        return 0, ""
    text = (r["stderr"] or r["stdout"] or "").strip()
    return 1, (text.splitlines() or ["build produced no image"])[-1]


# ── the corpus ──────────────────────────────────────────────────────────────

def example_sources() -> list:
    return sorted(glob.glob(os.path.join(HERE, "formal", "examples", "*.mojo")))


def memcheck_sources() -> list:
    """`formal/memcheck/*.mojo`: the programs that are ABOUT memory.

    The fuzzer's generated programs and the shipped examples are the wrong
    corpus for this tool for the same reason they are the right corpus for
    `formal_fuzz.py`: neither of them can express a heap object.  A program
    that does arithmetic has no `malloc` for `MallocScribble` to scribble, no
    allocation for `leaks` to count, and no aliasing for a use-after-free to
    come from -- and the formal path's ONLY heap is the one reached through the
    runtime dylib's allocator (`os._syscalls.str_alloc` and its kin).  So the
    rows that can find a heap defect live here, one file per defect class, each
    written so that the CLEAN answer and the DIRTY answer differ in the output
    rather than in an exit code nobody looks at.
    """
    return sorted(glob.glob(os.path.join(HERE, "formal", "memcheck", "*.mojo")))


def fuzz_sources(count: int, seed: str, mix: str, stmts) -> list:
    """Generated programs, from the fuzzer's own generator.

    `tools/formal_fuzz.py` is imported rather than its generator copied: the
    programs have to be the ones the differential corpus already measures, or
    this tool's findings would not be findings about a corpus anybody runs.
    `mix` and `stmts` are passed through unchanged for the same reason -- the
    mixes are the fuzzer's vocabulary, and a memcheck sweep over a mix the
    differential corpus never runs would be measuring a corpus nobody has.

    Nothing is written here -- `make_program` is a pure function of
    (seed, index, mix, stmts) and the file is written by the build step.
    """
    for p in (os.path.join(HERE, "tools"), HERE):
        if p not in sys.path:
            sys.path.insert(0, p)
    from tools.formal_fuzz import make_program
    out = []
    for i in range(count):
        out.append(("fuzz:%s:%s:%d" % (seed, mix, i),
                    make_program(seed, i, mix=mix, stmts=stmts)))
    return out


class Corpus:
    """(name, path) pairs: `path` is a file to compile."""

    def __init__(self):
        self.items = []

    def add_file(self, path: str):
        self.items.append((os.path.basename(path), path))

    def add_text(self, name: str, text: str, workdir: str):
        path = os.path.join(workdir, "src", name.replace(":", "_") + ".mojo")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        self.items.append((name, path))

    def __len__(self):
        return len(self.items)


# ── the instruments ─────────────────────────────────────────────────────────

#: Address-space ceiling for one instrumented run, in GB.  This exists because
#: the corpus can produce a RUNAWAY and a runaway is the most expensive thing
#: this tool can do: measured 2026-10-05, a `while i < 64:` over an uninitialised
#: `i` allocated until the machine was out of memory -- 15 GB RSS on one image --
#: and the whole sweep died of a `memcap` BREACH instead of reporting the
#: program that did it.  2 GB is three orders of magnitude above what any
#: program in this corpus needs (the largest measured peak for one image is
#: 1.6 MB) and four below the machine's budget, so it fires on a runaway and on
#: nothing else.
IMAGE_AS_LIMIT_GB = 2

MEMCAP = os.path.join(HERE, "tools", "memcap.py")
RUNLOG_DIR = os.path.join(DEFAULT_WORKDIR, "runlog")
BREACH_RE = re.compile(r"^memcap: BREACH\b", re.M)


def _capped(argv: list, tag: str) -> tuple:
    """`argv` behind this tree's own process-tree memory ceiling.

    `tools/memcap.py` rather than an `RLIMIT_AS` set in a `preexec_fn`, and the
    reason is measured rather than stylistic.  Two dead ends first: `preexec_fn`
    is unsafe in a program with threads (this tool runs a thread pool) and the
    version that used it died with `subprocess.SubprocessError: Exception
    occurred in preexec_fn` on the second row; and `sh -c 'ulimit -v ...'` is not
    available on Darwin at all -- `ulimit: virtual memory: cannot modify limit:
    Invalid argument`, because macOS's `RLIMIT_AS`/`RLIMIT_RSS` are not settable
    by a non-root process (CPython's `resource.setrlimit` raises `ValueError:
    current limit exceeds maximum limit` for every one of them).  `memcap` is the
    mechanism this repository already uses for exactly this, it measures the
    whole TREE rather than one address space, and it returns the child's exit
    status, so a runaway becomes one row instead of one dead sweep.

    THE CHILD'S OUTPUT GOES TO FILES, and that is not tidiness.  `memcap` prints
    its banner and its verdict to STDOUT -- deliberately, so that a caller can
    read them (see `tools/procrun.py`'s use of it) -- which means with a pipe on
    stdout the two are one stream.  Measured: every row came back
    NONDETERMINISTIC with `memcap: done, peak 0.0 GB across up to 1 procs` inside
    the program's own output, and a sweep at `--jobs 4` disagreed with itself
    only because the "up to N procs" count changed.  So the shell inside
    `memcap` redirects the image's own stdout and stderr to per-run files and
    this function returns them alongside memcap's lines.
    """
    out = os.path.join(RUNLOG_DIR, "%s.out" % tag)
    err = os.path.join(RUNLOG_DIR, "%s.err" % tag)
    os.makedirs(RUNLOG_DIR, exist_ok=True)
    for f in (out, err):
        if os.path.exists(f):
            os.unlink(f)
    wrapped = [sys.executable, MEMCAP, "--limit-gb", str(IMAGE_AS_LIMIT_GB),
               "--label", "memcheck", "--",
               "/bin/sh", "-c", 'exec "$@" >"$MC_OUT" 2>"$MC_ERR"', "sh"] + argv
    return wrapped, out, err


def _run(argv: list, env: dict, timeout: int, tag: str = None) -> dict:
    """Run `argv`. {rc, stdout, stderr, ran_out, timed_out, cap}

    With a `tag` the run goes behind `memcap` and the process's streams are
    files; without one they are pipes.  The two are kept apart deliberately --
    see `_capped`.  `cap` is memcap's own output, which is where its BREACH
    verdict lives, and `ran_out` is that verdict pre-decided, so no caller has
    to know that memcap prints its verdicts to stdout and exits 0.
    """
    out = err = None
    if tag:
        argv, out, err = _capped(argv, tag)
        env = dict(env)
        env["MC_OUT"] = out
        env["MC_ERR"] = err
    timed_out = False
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout, env=env)
        rc, cap = p.returncode, p.stdout
    except subprocess.TimeoutExpired:
        rc, cap, timed_out = None, "", True
    except OSError as e:
        return {"rc": None, "stdout": "", "stderr": "%s" % e, "cap": "",
                "ran_out": False, "timed_out": False}
    if out:
        return {"rc": rc, "stdout": _read(out), "stderr": _read(err),
                "cap": cap, "ran_out": bool(BREACH_RE.search(cap)),
                "timed_out": timed_out}
    return {"rc": rc, "stdout": p.stdout if not timed_out else "",
            "stderr": p.stderr if not timed_out else "", "cap": "",
            "ran_out": False, "timed_out": timed_out}


LEAK_RE = re.compile(r"(\d+)\s+leaks?\s+for\s+(\d+)\s+total leaked bytes")
NODES_RE = re.compile(r"(\d+)\s+nodes malloced for\s+(\d+)\s*(\w*)")


def leaks_of(path: str, backend: str, tag: str = None) -> dict:
    """`leaks --atExit` on one image. {leaks, bytes, nodes, ok, why}

    Uncapped by default.  `leaks` is the instrument, and an instrument that is
    itself under a memory ceiling is an instrument whose report depends on the
    ceiling: the measured peak of a healthy run is 0.1 GB, so 2 GB is two orders
    away, but the reason to leave it off is that a leak REPORT must be able to
    describe a process that used a lot of memory.
    """
    env = dict(os.environ)
    env.update(fixed_env())
    argv = run_argv(path, backend, tool="leaks")
    r = _run(argv, env, LEAKS_TIMEOUT)
    text = r["stdout"] + r["stderr"] + r["cap"]
    m = LEAK_RE.search(text)
    if not m:
        lines = (r["stderr"] or r["cap"] or "").strip().splitlines()
        return {"leaks": None, "bytes": None, "nodes": None, "ok": False,
                "ran_out": r["ran_out"], "timed_out": r["timed_out"],
                "why": (lines or ["no leak report"])[0][:200]}
    n = NODES_RE.search(text)
    return {"leaks": int(m.group(1)), "bytes": int(m.group(2)),
            "nodes": int(n.group(1)) if n else None, "ok": True,
            "ran_out": r["ran_out"], "timed_out": r["timed_out"], "why": ""}


def harness_path(workdir: str, backend: str) -> str:
    d = os.path.join(workdir, "harness")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "poison_%s.py" % backend)
    with open(path, "w") as f:
        f.write(HARNESS % {"span": POISON_SPAN, "word": POISON_WORD,
                           "names": POISON_REGISTERS[backend]})
    return path


def poison_of(path: str, backend: str, workdir: str, tag: str) -> dict:
    """Run `path` under the stack+register poison. {rc, stdout, stderr, painted}

    `process launch --stdout/--stderr` give the DEBUGGEE its own files, rather
    than sharing lldb's pipe.  That matters: without it the program's stdout
    and lldb's own chatter are one stream and can only be separated by
    pattern-matching lldb's lines out of the program's answer, which is
    precisely the wrong direction -- a program's output is the thing under
    test and must not be filtered.
    """
    entry = macho_entry(path)
    if entry is None:
        return {"rc": None, "stdout": "", "stderr": "no LC_MAIN in image",
                "painted": False, "ran_out": False, "timed_out": False}
    addr, _text = entry
    script = harness_path(workdir, backend)
    outf = os.path.join(workdir, "log", "%s.%s.out" % (tag, backend))
    errf = os.path.join(workdir, "log", "%s.%s.err" % (tag, backend))
    os.makedirs(os.path.dirname(outf), exist_ok=True)
    for f in (outf, errf):
        if os.path.exists(f):
            os.unlink(f)
    env = dict(os.environ)
    env.update(fixed_env())
    argv = ["lldb", "-b",
            "-o", "settings set interpreter.echo-commands false",
            "-o", "process launch --stop-at-entry --stdout %s --stderr %s"
                  % (outf, errf),
            "-o", "b *0x%x" % addr,
            "-o", "continue",
            "-o", "command script import %s" % script,
            "-o", "continue",
            "--", path]
    # Capped as well as the plain runs: lldb and debugserver are ~200 MB
    # together, which is well inside the ceiling, and the DEBUGGEE is inside
    # their tree, so a program that allocates without bound dies here instead of
    # on the machine.
    r = _run(argv, env, LDB_TIMEOUT, tag="%s.%s.poison" % (tag, backend))
    out, err, cap = r["cap"] + r["stdout"], r["stderr"], r["cap"]
    painted = "MEMCHECK-PAINT sp=0x" in out
    if not painted:
        return {"rc": None, "stdout": "", "stderr": (out + err).strip()[:400],
                "painted": False, "ran_out": r["ran_out"],
                "timed_out": r["timed_out"]}
    # `lldb`'s own status line is already normalised the way `effective_status`
    # normalises memcap's: "exited with status = 6" for an exit, a `stop
    # reason:` line for a death, and the latter becomes a negative number here
    # for the same reason.
    status = _lldb_status(out, err)
    if isinstance(status, str) and status.startswith("signal:"):
        status = -1
    return {"rc": status, "stdout": _read(outf),
            "stderr": _read(errf), "painted": True, "ran_out": r["ran_out"],
            "timed_out": r["timed_out"]}


def _read(path: str) -> str:
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _lldb_status(out: str, err: str) -> int:
    """The program's exit status, read out of lldb's own line.

    `Process N exited with status = 3` for a normal exit, and a stop with a
    signal instead of that line when the program died.  `None` means "did not
    finish", which is the answer the poison run has to be able to give.
    """
    m = re.search(r"exited with status = (-?\d+)", out)
    if m:
        return int(m.group(1))
    if re.search(r"stop reason: (EXC_|signal|SIG)", out):
        m = re.search(r"stop reason: (\w+)", out)
        return "signal:" + (m.group(1) if m else "?")
    return None


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


# ── one measurement ─────────────────────────────────────────────────────────

CHILD_EXIT_RE = re.compile(r"^memcap: done, .*child exit (-?\d+)$", re.M)


def effective_status(rc, cap: str):
    """The process's exit status, with a signal death still NEGATIVE.

    `memcap` gets the status from `Popen.poll()` -- negative for a signal death
    -- PRINTS it and then `return rc`, so what reaches a caller of `memcap` as
    an exit code has been through `sys.exit(-6)` and is 250, while what it
    printed is `-6`.  The number that distinguishes "died" from "exited" is in
    the printed line, so it is read from there.

    Why that matters rather than being pedantry: `main`'s return value IS this
    path's exit status and it can be anything at all.  Measured: `formal/
    examples/neg.mojo` exits 246, `sqsum.mojo` exits 129, `bigconst.mojo`
    exits 170 -- and the first version of this tool read every one of them as
    CRASH because it guessed "128 or more means a signal" from the shell
    convention.  Three healthy examples were reported as dead processes.  A
    formal program that returns a large number is not a crash, and only the
    negative spelling of a status is a crash.
    """
    m = CHILD_EXIT_RE.search(cap or "")
    if m:
        return int(m.group(1))
    return rc


def _died(status) -> bool:
    return status is not None and status < 0


def _lived(status) -> bool:
    return status is not None and status >= 0


VERDICTS = ("MATCH", "NONDETERMINISTIC", "POISON-DIVERGES", "POISON-CRASH",
            "POISON-HANG", "POISON-RUNAWAY", "SCRIBBLE-DIVERGES",
            "SCRIBBLE-CRASH", "LEAK", "CRASH", "HANG", "RUNAWAY", "REFUSED")


def measure(name: str, source: str, backend: str, workdir: str) -> dict:
    """Every instrument on one image, and one verdict."""
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    image = os.path.join(workdir, "img", "%s.%s" % (stem, backend))
    os.makedirs(os.path.dirname(image), exist_ok=True)
    rc, why = build(source, image, backend)
    row = {"name": name, "backend": backend,
           # Relative, because the ledger is committed and an absolute path
           # under somebody else's worktree is noise in a diff and a lie in a
           # review.  The path is `build/formal_memcheck/img/<name>.<backend>`
           # under whichever `--workdir` the run used.
           "image": os.path.relpath(image, HERE),
           "built": rc == 0, "build_diagnostic": why[:400],
           "verdicts": [], "detail": {}}
    if rc != 0:
        row["verdict"] = "REFUSED"
        return row

    plain = dict(os.environ)
    plain.update(fixed_env())
    argv = run_argv(image, backend)

    base = "%s.%s" % (stem, backend)
    r1 = _run(argv, plain, RUN_TIMEOUT, tag=base + ".base1")
    r2 = _run(argv, plain, RUN_TIMEOUT, tag=base + ".base2")
    rc1 = effective_status(r1["rc"], r1["cap"])
    out1 = r1["stdout"]
    row["detail"]["baseline"] = {"rc": rc1, "digest": digest(out1),
                                 "bytes": len(out1), "stdout": out1[:400],
                                 "stderr": r1["stderr"][:400]}

    scribble_env = dict(plain)
    scribble_env.update(MALLOC_DEBUG)
    r3 = _run(argv, scribble_env, RUN_TIMEOUT, tag=base + ".scribble")
    rc3 = effective_status(r3["rc"], r3["cap"])
    out3 = r3["stdout"]
    row["detail"]["scribble"] = {"rc": rc3, "digest": digest(out3),
                                 "bytes": len(out3), "stderr": r3["stderr"][:400]}

    lk = leaks_of(image, backend, tag=base + ".leaks")
    row["detail"]["leaks"] = lk

    # The plain run's own verdicts first, because they decide whether the
    # poison instrument has anything to compare against.  A runaway or a hang
    # has no answer, and running lldb on it would add LDB_TIMEOUT to every such
    # row for nothing -- so the run is skipped and the row says why, rather than
    # the sweep spending two minutes per runaway finding out what the baseline
    # already said.
    v = []
    if r1["ran_out"] or r3["ran_out"]:
        v.append("RUNAWAY")
    elif r1["timed_out"]:
        v.append("HANG")
    elif _died(rc1):
        v.append("CRASH")

    if "RUNAWAY" in v or "HANG" in v:
        poison = {"rc": None, "stdout": "",
                  "stderr": "skipped: the baseline run did not finish",
                  "painted": False, "ran_out": False, "timed_out": False}
    else:
        poison = poison_of(image, backend, workdir, stem)
    row["detail"]["poison"] = {"rc": poison["rc"], "painted": poison["painted"],
                               "digest": digest(poison["stdout"]),
                               "bytes": len(poison["stdout"]),
                               "stdout": poison["stdout"][:400],
                               "ran_out": poison["ran_out"],
                               "timed_out": poison["timed_out"],
                               "stderr": poison["stderr"][:200]}

    if out1 != r2["stdout"] or rc1 != effective_status(r2["rc"], r2["cap"]):
        v.append("NONDETERMINISTIC")
    # A baseline that already CRASHED has no answer to compare against, so no
    # POISON-* verdict is reported for it: the crash IS the finding, and a
    # second one derived from it is noise that differs by how each debugger
    # words a signal.  Measured: `blob_double_free` (which the malloc zone
    # aborts) came back POISON-HANG on arm64 and POISON-DIVERGES on x86-64 from
    # the same single abort -- `memcap` reports the child as 250 and lldb
    # reports it as 6 on one architecture and as "still stopped" on the other.
    # Both architectures now say CRASH.
    if not v:
        if poison["painted"]:
            if poison["ran_out"]:
                v.append("POISON-RUNAWAY")
            elif poison["timed_out"] or poison["rc"] is None:
                v.append("POISON-HANG")
            elif poison["rc"] != rc1 or poison["stdout"] != out1:
                crashed = _lived(rc1) and _died(poison["rc"])
                v.append("POISON-CRASH" if crashed else "POISON-DIVERGES")
        else:
            row["detail"]["poison_error"] = poison["stderr"]
    if rc3 != rc1 or out3 != out1:
        crashed = _lived(rc1) and _died(rc3)
        v.append("SCRIBBLE-CRASH" if crashed else "SCRIBBLE-DIVERGES")

    if lk["ok"] and lk["leaks"]:
        v.append("LEAK")

    row["verdicts"] = v
    row["verdict"] = v[0] if v else "MATCH"
    return row


# ── the ledger ──────────────────────────────────────────────────────────────


def ledger_key(row: dict) -> str:
    return "%s|%s" % (row["name"], row["backend"])


def load_ledger(path: str) -> dict:
    try:
        with open(path) as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return {}
    return payload.get("rows", {})


def write_ledger(path: str, rows: dict, meta: dict):
    payload = {
        "_comment": ("The clean baseline for tools/formal_memcheck.py: one row "
                     "per (program, backend) with the baseline stdout digest, "
                     "exit status, leak count and verdict. Written only by "
                     "--write-ledger; read by every run to report DRIFT."),
        "meta": meta,
        "rows": rows,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")


# ── the run ─────────────────────────────────────────────────────────────────


def collect(args) -> Corpus:
    """The corpus, in the order the flags ask for.

    `--program` is additive and the rest are not, so "check these two files"
    means two files rather than two files plus whatever the defaults are.
    """
    c = Corpus()
    if args.program:
        for p in args.program:
            c.add_file(os.path.abspath(p))
        return c
    if args.examples:
        for p in example_sources():
            c.add_file(p)
    if args.memcheck:
        for p in memcheck_sources():
            c.add_file(p)
    if args.fuzz:
        os.makedirs(os.path.join(args.workdir, "src"), exist_ok=True)
        for name, text in fuzz_sources(args.fuzz, args.seed, args.mix,
                                       (args.stmts_lo, args.stmts_hi)):
            c.add_text(name, text, args.workdir)
    if not c.items:
        # The default run is both shipped corpora: the heap rows are what can
        # find a heap defect and the examples are the arithmetic regression
        # net, and neither is interesting without the other.
        for p in memcheck_sources() + example_sources():
            c.add_file(p)
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--program", action="append",
                    help="a source file to check (repeatable)")
    ap.add_argument("--fuzz", type=int, default=0,
                    help="generate N programs from tools/formal_fuzz.py")
    ap.add_argument("--seed", default="memcheck")
    ap.add_argument("--mix", default="core",
                    help="tools/formal_fuzz.py MIXES key")
    ap.add_argument("--stmts-lo", type=int, default=5)
    ap.add_argument("--stmts-hi", type=int, default=12)
    ap.add_argument("--examples", action="store_true",
                    help="formal/examples/*.mojo")
    ap.add_argument("--memcheck", action="store_true",
                    help="formal/memcheck/*.mojo -- the heap rows (the default "
                         "corpus, with --examples, when nothing else is named)")
    ap.add_argument("--backends", default="arm64,x86_64")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="stop after N programs")
    ap.add_argument("--workdir", default=DEFAULT_WORKDIR)
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--write-ledger", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated verdicts to print")
    ap.add_argument("--fail-on", default="",
                    help="comma-separated verdicts that make the exit status "
                         "non-zero; the default is DRIFT alone, because a "
                         "memory-safety corpus has findings by design")
    args = ap.parse_args(argv)

    backends = [b for b in args.backends.split(",") if b]
    for b in backends:
        if b not in BACKENDS:
            ap.error("unknown backend %r" % b)
    os.makedirs(args.workdir, exist_ok=True)
    corpus = collect(args)
    if args.limit:
        corpus.items = corpus.items[:args.limit]
    if not corpus.items:
        ap.error("empty corpus")

    jobs = []
    for name, path in corpus.items:
        for backend in backends:
            jobs.append((name, path, backend))

    print("formal_memcheck: %d programs x %d backends = %d images, "
          "%d jobs, workdir %s"
          % (len(corpus), len(backends), len(jobs), args.jobs, args.workdir))

    rows = {}
    counts = {}
    findings = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futs = {pool.submit(measure, n, p, b, args.workdir): (n, b)
                for n, p, b in jobs}
        for fut, (n, b) in futs.items():
            row = fut.result()
            rows[ledger_key(row)] = row
            counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
            if row["verdicts"] or row["verdict"] in ("CRASH", "REFUSED"):
                findings.append(row)

    prev = load_ledger(args.ledger)
    drift = []
    for key, row in sorted(rows.items()):
        old = prev.get(key)
        if old and old.get("verdict") != row["verdict"]:
            drift.append((key, old.get("verdict"), row["verdict"]))

    want = [v.strip() for v in args.only.split(",") if v.strip()]
    for row in sorted(findings, key=lambda r: (r["backend"], r["name"])):
        if want and row["verdict"] not in want and not (
                set(row["verdicts"]) & set(want)):
            continue
        print("== %-14s %-8s %s" % (row["verdict"], row["backend"], row["name"]))
        for key, val in sorted(row["detail"].items()):
            print("     %-9s %s" % (key, json.dumps(val, sort_keys=True)[:300]))
        if row["build_diagnostic"]:
            print("     build     %s" % row["build_diagnostic"])
        if row.get("verdicts"):
            print("     all       %s" % ",".join(row["verdicts"]))

    for key, was, now in drift:
        print("== DRIFT         %-8s %s: %s -> %s"
              % (rows[key]["backend"], rows[key]["name"], was, now))

    print("--- %d images: %s" % (len(rows), ", ".join(
        "%s=%d" % kv for kv in sorted(counts.items()))))
    print("--- drift vs ledger: %d" % len(drift))

    if args.write_ledger:
        write_ledger(args.ledger, rows, {
            "programs": len(corpus),
            "backends": backends,
            "seed": args.seed,
            "mix": args.mix,
            "fuzz": args.fuzz,
        })
        print("--- ledger written: %s" % args.ledger)

    # The EXIT STATUS answers "did anything change against the ledger", not "did
    # anything print a verdict".  A corpus of memory-safety rows has findings
    # BY DESIGN -- `blob_alloc_leak` exists to report LEAK, `blob_double_free`
    # to report CRASH -- so a status that failed on any finding would be a tool
    # that can never be green and therefore says nothing.  `--fail-on` moves
    # the question if a caller wants the other one.
    if args.fail_on:
        want = {v.strip() for v in args.fail_on.split(",") if v.strip()}
        hit = sorted({v for row in rows.values() for v in (row["verdicts"] or [row["verdict"]])} & want)
        if hit:
            print("--- failing on %s: %s" % (args.fail_on, ",".join(hit)))
            return 1
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())