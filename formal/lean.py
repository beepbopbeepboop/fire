"""Everything this repository knows about running Lean 4.

Two halves that used to be one file's business and are now clearly two:
`run_lean` below is the ONE launcher (bounds, flags, the kill, the verdict),
and everything after it is what this repository does with a Lean run — the
`.olean` build and its currency rules, the hole census, the verdict cache.

## The bounds, and where the numbers come from

**Every `lean` in this tree is launched by `run_lean`, and every run has an
upper bound on wall time, on total CPU across the whole process tree, and in
Lean's own `maxHeartbeats`.** This is not tidiness. On 2026-10-02 there were
ten `lean` processes on this machine that had run for HUNDREDS of CPU-hours and
the user killed them by hand; a valid inductive proof here checks in seconds to
minutes, so those were non-terminating elaborations, and every launch site that
had a bound at all had a WALL bound only (`subprocess.run(timeout=1200)`, and
`x86_64_endtoend_test.py` had none). `maxHeartbeats` does not catch them either:
it meters the elaborator's allocations, while the work that spins in these
proofs is `native_decide` and kernel reduction, which is exactly what it does
not meter.

The three bounds, and what each one is for:

| bound | how | catches |
|---|---|---|
| wall | the launcher's own clock | a loop that sleeps, and a load-induced slowdown that never ends |
| CPU (whole tree) | `RLIMIT_CPU` via `preexec_fn` (SIGXCPU), and the `ps` walk in `procrun.tree_usage` for the descendants | a loop that spins: Lean's threads are many, so a proof can burn every core while its wall clock looks ordinary |
| heartbeats | `-T`, passed explicitly | a loop that is deterministic in allocation count, reported as a Lean ERROR with the declaration named, which is the only one of the three that says *where* |

**Sizes, measured on this tree (2026-10-02, arm64 M-series, the pinned
`leanprover/lean4:v4.32.2`, `-j 4`, an otherwise idle box; `FORMAL_LEAN_TRACE=1`
makes `run_lean` print the same three figures for every run it makes, so
re-measuring is one env var and not a re-derivation):**

| what | wall | CPU | peak RSS |
|---|---|---|---|
| `lib/ProofLib.olean` build — 27.0 MB | 112.0 s | 83.1 s | 7.82 GB |
| `lib/X86.olean` build — 6.6 MB | 6.0 s | 12.4 s | 1.36 GB |
| `lib/work.olean`, `lib/Refine.olean`, `lib/Contracts.olean` | 1.2–1.4 s | 0.5–1.3 s | ~1.2 GB |
| generated proof of `formal/examples/const2.mojo` — 139 KB | 8.6 s | 10.3 s | 1.54 GB |
| generated proof of `formal/examples/bitops.mojo` — 436 KB | 21.5 s | 31.0 s | 2.19 GB |
| generated proof of `formal/examples/augassign.mojo` — 421 KB | 20.9 s | 30.4 s | 2.15 GB |
| generated proof of `formal/examples/elif3.mojo` — 514 KB | 69.7 s | 63.8 s | 2.89 GB |
| generated proof of `formal/examples/count.mojo` — 384 KB | 79.7 s | 80.3 s | 2.71 GB |
| generated proof of `formal/examples/pow2.mojo` — 420 KB | 84.4 s | 90.7 s | 2.98 GB |
| generated proof of `formal/examples/sqsum.mojo` — 476 KB | 98.5 s | 102.2 s | 3.15 GB |
| generated proof of `formal/examples/wide_recv.mojo` — 703 KB (the largest file) | 93.4 s | 97.4 s | 3.00 GB |
| generated proof of `formal/examples/fib.mojo` (a known gap: rc=1) | 99.7 s | 100.2 s | 2.86 GB |
| generated proof of `formal/examples/udivmod.mojo` — 437 KB (**the slowest**) | 297.8 s | 219.2 s | 2.30 GB |

**Size does not predict cost**, and that is in the table rather than in a
warning: the largest generated proof here (`wide_recv`, 703 KB) checks in 93 s
while a 437 KB one (`udivmod`) takes 298 s. A bound sized by "the biggest file I
have seen" would have been set at 93 s and would have fired on a legitimate
proof.

So `PROOF_WALL_S = 1500` / `PROOF_CPU_S = 1500` is **5x the slowest legitimate
proof measured** (6.8x its CPU), and `LIBRARY_WALL_S = 1800` /
`LIBRARY_CPU_S = 1800` is **16x the slowest module build** — both far below
`tools/control.py guard`'s 45 min wall / 90 min CPU net, which exists to catch a
launcher that was never taught these bounds, not to be the bound.

The multiplier is on the slowest measurement rather than on a typical one, and
deliberately: `test_formal.py` runs up to 20 examples at once, each with its own
`lean`, so a proof that takes 298 s alone can take several times that on a loaded
box — and a bound that fires on a legitimate proof is worse than a bound that
waits, because it is a false red in the gate and it looks like a regression. The
cost of being generous is bounded and paid in the right currency: a runaway is
stopped at 25 minutes of CPU, which is a quarter of the hour the guard net would
otherwise have let it run, and `test_formal.py`'s own 900 s `BUILD_TIMEOUT`
(unchanged, and it kills the process group) is the tighter bound in that one
path.

Two of those rows are the reason a wall-only bound was never enough, and they
are in the measurements rather than in an argument: `X86` burned **12.4 s of
CPU in 6.0 s of wall** and every generated proof burned CPU *greater* than its
own wall clock. Lean's elaborator is a thread pool, so "how long has it been
running" and "how much has it cost" are different numbers and only one of them
was being measured.

**The escape hatch is the library build and nothing else.**
`FORMAL_LEAN_LIBRARY_WALL_S` / `FORMAL_LEAN_LIBRARY_CPU_S` raise the bound for
`ensure_library` and `library_census`, because that is the one legitimate step
whose cost this project cannot bound in advance (it is a function of how big
`lib/*.lean` has grown). A proof bound that any environment could raise is not a
bound: a runaway elaboration setting `FORMAL_LEAN_WALL_S=999999` would be
indistinguishable from a proof that genuinely needs the time. Both knobs exist
because "make the number bigger" is what an operator does at 2am, and it should
be possible to do it in one env var rather than by editing a policy constant.

**A breach is a verdict of its own, not a failure and not a pass.** `run_lean`
returns it in `LeanRun.exceeded` and every caller turns it into a message that
names the bound it broke; it is NOT published to the verdict cache, because a
breach is a fact about this machine at this moment (how loaded it was, how many
proofs ran at once) rather than a property of the proof's bytes — caching it is
how a red becomes permanent (`bugs/FORMAL_dylib_export_loops_and_frame_bounds.md`).
And it is never silently `0` holes: a killed elaboration measured nothing, so
the hole census reports UNMEASURED for it.

The one thing this does NOT fix is a proof that needs more than the bound: it
converts an unbounded hang into a loud, reproducible, one-line failure that says
which bound was broken. What spins is a separate question, and the one case ever
MEASURED is now fixed rather than documented: `bv_decide` on a 14-fold composed
`Arm64State` normalised its own goal with a `simp` -- the runner's `if pc = pc
then .. else ..`, one per step, around the whole state -- which `maxHeartbeats`,
`maxSteps` and `maxRecDepth` all failed to meter, three separate measurements.
`FORMAL.md` §12 and `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` §1 carry
the numbers and the fix; the lesson for this module is the one that outlives it:
a budget was the wrong instrument three times over, so the bound here is the
instrument and the emitter owes the tree goals small enough to need it.
"""
import collections
import contextlib
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

# Dependency order: X86 needs ProofLib, and work.lean re-exports it so the
# generated proof files (which import ProofLib + work + Refine) get the x86-64
# model without naming a fourth module.
# Order is build order: `Contracts` imports `ProofLib` and `Refine`, so it
# must come after them.
#
# `IEEE754` is FIRST and imports nothing: the binary64 semantics, stated over
# the `UInt64` bit pattern both backends carry a `double` in.  It is a separate
# module rather than a section of `ProofLib.lean` for the reason every change to
# `ProofLib.lean` is expensive — it is a 400KB file several branches edit, and
# its `.olean` is 27MB and ~90s to produce, so a module that is 1/200th of the
# semantics and 1/200th of the edit surface does not belong inside it.  Nothing
# imports it yet: the FP step functions that would are `arm64_step`'s and
# `x86_64_step`'s, and giving either state a second register file is the step
# that has to land first (`bugs/FORMAL_float_step_functions.md`).  Until then it
# is INFRASTRUCTURE, and it is in this tuple rather than unbuilt because the
# hole census and the `.olean` currency check read the tuple — a module outside
# it is a module nothing checks.
# `Specs` is LAST and imports only `ProofLib`: it is the INDEPENDENT
# specification layer — reference definitions for the classic example programs,
# written by hand in Lean's own `Nat`/`Int`/`List` rather than derived from a
# source file the same way `mojo` is.  It is last because it is the only module
# no other library module imports, and a generated proof imports it only when
# its source carries an `@refines(...)` annotation.
LIBRARY_MODULES = ("IEEE754", "ProofLib", "X86", "work", "Refine", "Contracts",
                   "Specs")
VERDICT_EXT = ".leanverdict"
# Where a library module's own hole census is stored, beside the .olean it was
# measured from and under the same key — so a cas HIT on the .olean is a hit on
# its census, and a tree whose .oleans predate the census is the only case that
# has to be measured (see `library_census`).
CENSUS_EXT = ".libcensus"
_OLEAN_DIGESTS: dict = {}
# stem -> (n_sorries, (names...)), filled by ensure_library for this process and
# read by library_census so the common case is a dict lookup, not a cas probe.
_LIB_CENSUS: dict = {}


def _default_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pinned_toolchain(root: str) -> str | None:
    """The toolchain named by <root>/lean-toolchain, e.g. leanprover/lean4:v4.32.2."""
    try:
        with open(os.path.join(root, "lean-toolchain")) as f:
            spec = f.read().strip()
    except OSError:
        return None
    return spec or None


def elan_toolchain_binary(spec: str) -> str | None:
    """Concrete <elan>/toolchains/<mangled>/bin/lean for a lean-toolchain spec.

    elan's on-disk directory name escapes the spec separators by repeating the
    dash: '/' becomes '--' and ':' becomes '---'. Resolving the pinned
    toolchain directly (instead of running the elan shim) is what keeps
    proof checking from silently using - or downloading - whatever toolchain
    the shim's default happens to be, which is what a shim invoked with a cwd
    outside the repo does.
    """
    elan_home = os.environ.get("ELAN_HOME") or os.path.expanduser("~/.elan")
    mangled = spec.replace("/", "--").replace(":", "---").replace("@", "---")
    candidate = os.path.join(elan_home, "toolchains", mangled, "bin", "lean")
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return None


def find_lean(repo_root: str | None = None) -> str | None:
    root = repo_root or _default_root()
    spec = pinned_toolchain(root)
    # `LEAN_BIN` is beside `LEAN` and is what `formal/x86_64_endtoend_test.py`
    # read, so both spellings resolve here rather than one of them keeping a
    # hard-coded elan path beside the resolver that exists to avoid exactly
    # that.
    candidates = [os.environ.get("LEAN"), os.environ.get("LEAN_BIN"),
                  os.path.join(root, ".pixi", "envs", "default", "bin", "lean")]
    if spec:
        pinned = elan_toolchain_binary(spec)
        if pinned:
            candidates.append(pinned)
    candidates.append(shutil.which("lean"))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


# ── The launcher: the ONE way this tree runs Lean ──────────────────────────
#
# The numbers and the measurements behind them are in this module's docstring;
# what is here is the mechanism. Three bounds, because they catch three
# different failures and none of them catches all three:
#
#   * WALL (`time.monotonic` around the child) — catches a loop that does not
#     saturate the machine and a load-induced slowdown that never ends.  Cheap
#     to check, so it is checked four times a second.
#   * CPU (whole tree) — catches a loop that DOES saturate the machine, which is
#     what these proofs actually do: `lean` runs a thread pool, so an
#     elaboration that will not terminate can burn every core of the box while
#     its wall clock looks unremarkable.  Enforced twice, on purpose:
#     `RLIMIT_CPU` in the child (SIGXCPU, the kernel's own meter, which fires
#     whatever the parent is doing) and the `ps` walk over the tree (which is
#     the only thing that can see a DESCENDANT's CPU — `RLIMIT_CPU` is
#     inherited per process, so `native_decide`'s out-of-process compiler gets
#     its own fresh limit and N of them add up to N times the bound).
#   * HEARTBEATS (`-T`) — catches a loop that is deterministic in allocation
#     count, and it is the only one of the three that reports WHERE: a Lean
#     error naming the declaration, in the file's own diagnostics, in the
#     output every caller already parses.
#
# The kill is always the whole TREE (`procrun.kill_group` walks `ps` and kills
# children before parents, then the group), plus a group sweep after the fact
# for the one path the launcher does not control — see `_kill_leftovers`.
#
# `preexec_fn` rather than a shell wrapper or a `sitecustomize`: it is the only
# one of the three that can set an rlimit in the child without putting a shell
# between us and `lean` (so Lean's own exit code, and its diagnostics on the
# streams we captured, stay intact).  It is safe here because this module's
# callers are single-threaded while a run is in flight — which is the same
# condition `subprocess`'s own documentation states for it.

_ROOT = _default_root()
if _ROOT not in sys.path:
    sys.path.append(_ROOT)
from tools import procrun  # noqa: E402 — the tree walk and the kill, shared

# Wall/CPU bounds for ONE generated proof, and for ONE library `.olean` build.
# Sized from the measurements in the module docstring: ~6x the slowest
# legitimate proof, and ~15x the slowest module build.  Both are far tighter
# than `tools/control.py guard`'s 45 min / 90 min net, which is the net UNDER
# every launcher that never got here.
PROOF_WALL_S = 1500.0
PROOF_CPU_S = 1500.0
LIBRARY_WALL_S = 1800.0
LIBRARY_CPU_S = 1800.0
# Lean's own bounds.  `-M` is Lean's own memory ceiling and it is NOT the
# project's 4 GB line: that line is a DEBT standard for what a job should cost
# (`bugs/PERF_memory_over_4gb_is_a_bug.md`), and enforcing it by capping Lean is
# not paying the debt, it is breaking the build — measured, not assumed: with
# `-M 4096` the `lib/ProofLib.lean` build fails at line 3808 with "(kernel)
# excessive memory consumption detected" and peaks at 7.8 GB, so a 4 GB ceiling
# is not a tighter policy, it is a red suite.  What it must be is ABOVE what the
# real work needs, so a runaway is stopped and a legitimate build is not; the
# over-4 GB fact is `prooflib`'s own `memwhy` in tools/suite.py and is filed
# there.
#
# Two ceilings because there are two kinds of work: a generated proof checks a
# ~700 KB file of `native_decide` goals and needs a small fraction of what
# building the 27 MB `.olean` library does, and one number for both would have to
# be the larger.
LEAN_THREADS = 4
LEAN_MEMORY_MB = 6144          # one generated proof
LIBRARY_MEMORY_MB = 12288      # one lib/*.olean build
LEAN_HEARTBEATS = 200000
# How often each bound is checked. The wall clock is free, so it is read often;
# the CPU walk costs one `ps` (~50-100 ms on this platform), so it is not.
_WALL_POLL_S = 0.25
_CPU_POLL_S = 2.0
# RLIMIT_CPU's HARD limit, this far past its soft one: a process that somehow
# handles SIGXCPU gets SIGKILLed rather than left spinning.
_CPU_HARD_GRACE_S = 30.0


#: One bounded run. `exceeded` is the verdict; `pgid` is the process group the
#: run was given, which is the handle a caller needs to check (or reap) that
#: nothing outlived it — `procrun.kill_group` has already done that by the time
#: this is returned, so it is here to be ASSERTED, not to be used.
LeanRun = collections.namedtuple(
    "LeanRun", "returncode stdout stderr exceeded wall_s cpu_s peak_rss pgid")


def lean_flags(mem_mb: int | None = None, heartbeats: int | None = None,
               threads: int | None = None) -> list:
    """Lean's OWN bounds, as argv, in the order `lean` documents them."""
    return ["-j", str(LEAN_THREADS if threads is None else threads),
            "-M", str(LEAN_MEMORY_MB if mem_mb is None else mem_mb),
            "-T", str(LEAN_HEARTBEATS if heartbeats is None else heartbeats)]


def library_bounds() -> tuple:
    """`(wall_s, cpu_s)` for a library `.olean` build or a census run.

    The ONE place the policy can be raised, and by environment variable only,
    because the library build is the one legitimate step whose cost cannot be
    bounded in advance — it is a function of how large `lib/*.lean` has grown,
    and it is already the slowest thing here by an order of magnitude.

    A PROOF bound is deliberately not env-raisable: a bound the environment can
    lift is not a bound, and the thing that needs lifting during a runaway is
    exactly the thing an operator would lift it for.
    """
    def env_seconds(name, default):
        raw = (os.environ.get(name) or "").strip()
        try:
            value = float(raw)
        except ValueError:
            return default
        return value if value > 0 else default
    return (env_seconds("FORMAL_LEAN_LIBRARY_WALL_S", LIBRARY_WALL_S),
            env_seconds("FORMAL_LEAN_LIBRARY_CPU_S", LIBRARY_CPU_S))


def _cpu_rlimit(cpu_s: float):
    """A `preexec_fn` that puts `RLIMIT_CPU` on the child.

    The kernel meters the process's total CPU across every thread and sends
    SIGXCPU at the soft limit, which is why this is the enforcement path and the
    `ps` walk is the reporting one: the poll can miss a spike between two
    samples, the rlimit cannot.

    Clamped to whatever hard limit we inherited, because raising one is a
    privilege this process does not have and `setrlimit` fails outright rather
    than clamping — which would lose the bound entirely on a machine that
    started `lean` under a tight `ulimit -t`.
    """
    def install():
        import resource
        try:
            soft_now, hard_now = resource.getrlimit(resource.RLIMIT_CPU)
            soft = int(cpu_s)
            hard = soft + int(_CPU_HARD_GRACE_S)
            if hard_now != resource.RLIM_INFINITY:
                hard = min(hard, hard_now)
                soft = min(soft, hard)
            resource.setrlimit(resource.RLIMIT_CPU, (soft, hard))
        except (OSError, ValueError, ImportError):
            # A platform without RLIMIT_CPU keeps the wall bound and the tree
            # walk, which is a weaker bound rather than no bound.  Silently,
            # because a launcher that refuses to run is worse.
            pass
    return install


def _kill_leftovers(pgid: int) -> int:
    """SIGKILL anything still alive in a finished run's process group.

    The one hole in `kill_group`, and it is a real one: `RLIMIT_CPU` fires
    INSIDE the child, so the launcher never chose that moment and the child's
    descendants are already reparented to init by the time the poll notices —
    which is exactly when a `ps` walk by ppid finds nothing.  A process group
    is inherited by every descendant and outlives the process that created it,
    so this is the handle that still works.  Returns how many it killed, which
    is worth counting: a non-zero count on a run that was never killed is a
    process that outlived its bound, and that is the bug this whole module is
    about.
    """
    killed = 0
    for pid in procrun.group_pids(pgid):
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except (ProcessLookupError, PermissionError, OSError):
            pass
    return killed


def run_lean(lean: str, args, cwd: str | None = None, env: dict | None = None,
             wall_s: float | None = None, cpu_s: float | None = None,
             mem_mb: int | None = None, heartbeats: int | None = None,
             threads: int | None = None) -> LeanRun:
    """Run `lean` under every bound, and say which one it hit.

    `wall_s`/`cpu_s` default to the PROOF bounds; a library build passes
    `library_bounds()`.  Output is captured through temp files rather than
    pipes for the same reason `tools/procrun.py` does it that way: this polls
    the child instead of blocking in `communicate`, and a pipe nobody is
    draining is a deadlock the moment a proof prints more than a buffer.

    **`exceeded` is the field every caller must read.**  It is `None` for a run
    that finished — whatever its exit code — and a sentence naming the bound it
    broke otherwise.  `ok` alone cannot express it: Lean's own exit code for a
    killed elaboration is `-SIGXCPU` or `-SIGKILL`, which a caller that only
    compares against 0 reports as "lean failed", and one that compares against
    `None` reports as success.
    """
    wall_s = PROOF_WALL_S if wall_s is None else float(wall_s)
    cpu_s = PROOF_CPU_S if cpu_s is None else float(cpu_s)
    if not lean:
        # `find_lean` returning None is what every caller tests for, but a
        # caller that passes one straight through used to get a TypeError from
        # `Popen` — a traceback about `subprocess`, not about the missing
        # toolchain. Said in the verdict's own language instead.
        return LeanRun(None, "", "", "lean not found (see ./lean-toolchain)",
                       0.0, 0.0, 0, 0)
    argv = [lean] + lean_flags(mem_mb, heartbeats, threads) + [str(a) for a in args]
    with tempfile.TemporaryFile(mode="w+b") as out, \
            tempfile.TemporaryFile(mode="w+b") as err:
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=env,
                                    stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=err, start_new_session=True,
                                    preexec_fn=_cpu_rlimit(cpu_s))
        except OSError as e:
            return LeanRun(None, "", "", f"lean could not be started: {e}",
                           0.0, 0.0, 0, 0)
        started = time.monotonic()
        deadline, cpu_at = started + wall_s, started
        exceeded, cpu, peak = None, 0.0, 0
        while True:
            rc = proc.poll()
            now = time.monotonic()
            if rc is not None:
                break
            if now >= deadline:
                exceeded = (f"lean exceeded {now - started:.0f}s wall "
                            f"(limit {wall_s:g}s) — killed, and this is NOT a "
                            f"verdict on the proof")
                break
            if now >= cpu_at:
                tables = procrun.ps_snapshot()
                spent, rss, _n = procrun.tree_usage(proc.pid, tables[0],
                                                     tables[1], tables[2])
                cpu, peak = max(cpu, spent), max(peak, rss)
                cpu_at = now + _CPU_POLL_S
                if spent > cpu_s:
                    exceeded = (f"lean exceeded {spent:.0f}s CPU across its "
                                f"process tree (limit {cpu_s:g}s) — killed, "
                                f"and this is NOT a verdict on the proof")
                    break
            time.sleep(_WALL_POLL_S)
        wall = time.monotonic() - started
        if exceeded is not None:
            procrun.kill_group(proc)
            # `kill_group` reaps the child itself (`kill_tree` waitpid()s it),
            # and `Popen` on a pid somebody else reaped reports **0** — which is
            # how a killed elaboration comes back looking like a proof that
            # checked. The status is forced here rather than left to whichever
            # `Popen` version is installed, because "no caller can read a bound
            # breach as a pass" is the whole point of this function.
            rc = -signal.SIGKILL
        else:
            rc = proc.returncode
            # The rlimit fires INSIDE the child, so the poll loop can see a
            # clean exit carrying a signal status and no breach to report. That
            # IS the breach, and a caller that only tests `returncode != 0`
            # would call it an ordinary elaboration failure.
            if rc is not None and rc < 0 and -rc == signal.SIGXCPU:
                exceeded = (f"lean exceeded {cpu_s:g}s CPU (limit {cpu_s:g}s, "
                            f"enforced by RLIMIT_CPU inside lean) — killed, "
                            f"and this is NOT a verdict on the proof")
            if rc is None:
                rc = proc.wait()
        if exceeded is None:
            _kill_leftovers(proc.pid)
        out.seek(0)
        err.seek(0)
        res = LeanRun(rc,
                      out.read().decode("utf-8", "replace"),
                      err.read().decode("utf-8", "replace"),
                      exceeded, wall, cpu, peak, proc.pid)
        if (os.environ.get("FORMAL_LEAN_TRACE") or "").strip():
            # One line per run, off by default because sixteen parallel proof
            # jobs do not need a commentary and the figures are what sized the
            # bounds in this module's docstring — so the way to re-measure them
            # is one env var, not a re-derivation from a bug doc.
            print(f"  [lean run: {os.path.basename(str(args[-1])) if args else lean}"
                  f" rc={res.returncode} wall={res.wall_s:.1f}s"
                  f" cpu={res.cpu_s:.1f}s peak={res.peak_rss / (1 << 30):.2f}GB"
                  f" bounds={wall_s:g}/{cpu_s:g}s"
                  + (f" EXCEEDED: {res.exceeded}" if res.exceeded else "")
                  + "]", file=sys.stderr)
        return res


@contextlib.contextmanager
def scratch_dir(prefix: str, base: str | None = None):
    """A PRIVATE directory for a generated `.lean` file, removed afterwards.

    `run_lean` above is the one launcher, and this is the one place a generated
    file is allowed to live. Both halves of that matter, and the reason is a bug
    this tree shipped: `formal/x86_64_model_test.py` and
    `formal/x86_64_model_coverage_test.py` each wrote their generated source to a
    hard-coded `os.path.join("/tmp", "<a fixed name>")` and handed it to `lean`
    BY RELATIVE NAME with `cwd` set there. Both are registered suite jobs, the
    corpus has several worktrees, and `tools/suite.py` runs `-j 18` — so two
    concurrent invocations wrote the SAME `Coverage.lean`, and the second
    writer's bytes were what the first invocation's `lean` read. The coverage
    file is 151 `native_decide` goals plus 482 hypothesis checks, so an
    interleaved read is not a small corruption, and it would be reported as "a
    form is not steppable" or "hypothesis N does not hold": a model or lemma
    bug, in the wrong file, in someone else's run. This is precisely the hazard
    `ensure_library` takes an exclusive `flock` over further down.

    So the directory is `mkdtemp` (0700, unique) rather than a named path, it is
    removed in a `finally` so a crashed run leaves nothing, and callers hand
    `lean` an ABSOLUTE path rather than a relative one — the cwd no longer has
    to be the directory, which is what made the shared name load-bearing.

    `base` defaults to `TMPDIR`, which `tempfile` already prefers, so a caller
    that must land inside the checkout (a sandbox with no writable `/tmp`, or a
    worker whose `TMPDIR` is the worktree's `.tmp`) needs no argument here; the
    parameter exists for the caller that wants a specific parent.
    """
    root = base if base else (os.environ.get("TMPDIR") or None)
    path = tempfile.mkdtemp(prefix=prefix + "-", dir=root)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _olean_key(stem: str, source: str, lean: str, source_digest: str = "") -> str:
    """CAS key for a library .olean: the source bytes, the module name and the
    toolchain. Lean's output for a given (source, version) pair is
    deterministic, so this is a hit on every machine and every rebuild after
    the first — ProofLib.olean alone is 27MB and takes ~90s to produce.

    `source_digest` is the EFFECTIVE digest (`_effective_digest`), not this
    module's own bytes, and that is load-bearing: `work.lean` imports `X86`,
    so an edit to `X86.lean` changes what `work.olean` MEANS while leaving
    `work.lean` byte-identical. Keyed on its own bytes alone, the cas would
    serve the `work.olean` elaborated against the previous X86 — the exact
    "wrong artifact served from cache, silently" failure the self-host
    fingerprint rules exist to prevent, one module down. It defaults to this
    module's own digest so a caller that has not computed the effective one
    gets the old key rather than a key with a hole in it."""
    import cas
    with open(source, "rb") as f:
        return "leanlib/" + cas.hash_parts(
            b"lean-olean-v2", stem.encode(), lean_version(lean).encode(),
            (source_digest or _sha256_file(source)).encode(), f.read())

def _library_is_current(source: str, olean: str, stamp: str,
                        source_digest: str) -> bool:
    """Is this .olean built from exactly this source AND the imports it names?

    Purely content-based, with no mtime in the decision: `touch
    lib/ProofLib.lean` (or a git checkout, or an editor that rewrites mtimes)
    must not cost a 27MB Lean rebuild, and an mtime rule cannot tell "touched"
    from "edited" — which is why a bare mtime check makes the whole formal
    suite mysteriously slow again after anything touches lib/. The stamp
    records the source digest the .olean was built from *and* a digest of the
    .olean itself, so an edit invalidates, a touch does not, and an .olean
    swapped out from under the stamp invalidates too.

    `source_digest` is the EFFECTIVE digest — this module's own bytes AND every
    library module it imports, transitively — and that is the second half of
    the rule. The stamp used to record this module's own bytes alone, so
    editing `X86.lean` left `work.olean` (built from `work.lean`, which
    `import X86`) in place: every later `lean` run then recompiled the stale
    import inside the checker, with no error anywhere and a memory bill an
    order of magnitude over the honest one. See `_effective_digest`."""
    if not (os.path.isfile(olean) and os.path.isfile(stamp)):
        return False
    try:
        with open(stamp) as f:
            recorded_source, recorded_olean = f.read().split()[:2]
    except (OSError, ValueError):
        return False
    if recorded_source != source_digest:
        return False
    return _digest(olean).hex() == recorded_olean


def _write_stamp(stamp: str, source: str, olean: str,
                 source_digest: str = "") -> None:
    """Record which source a .olean was built from, so a later run is a stat.

    `source_digest` is the EFFECTIVE digest the currency check compares
    against, for the reason `_effective_digest` gives; the default is this
    module's own bytes, which is what a tree with no imports has."""
    tmp = f"{stamp}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(f"{source_digest or _sha256_file(source)} "
                f"{_digest(olean).hex()}\n")
    os.replace(tmp, stamp)


def _module_imports(source: str) -> set:
    """The `LIBRARY_MODULES` names this library source's `import` lines name.

    Read from the source rather than hard-coded, because the import graph is
    the thing that has to stay right and a table beside it is a second copy of
    it to forget. `import Lean` and anything outside `LIBRARY_MODULES` are not
    this mechanism's business — those are pinned by the toolchain half of the
    key instead."""
    names = set()
    try:
        with open(source, "r", errors="replace") as f:
            for line in f:
                if not line.startswith("import "):
                    continue
                name = line[len("import "):].strip().split()
                if name:
                    names.add(name[0])
    except OSError:
        return names
    return names & set(LIBRARY_MODULES)


def _effective_digest(stem: str, lib_dir: str, _seen=None) -> str:
    """A digest over `stem`'s own source AND every library module it imports.

    **The staleness this closes.** A Lean `.olean` embeds its imports'
    definitions, so `work.olean` — built from `work.lean`, which is
    `import ProofLib` + `import X86` and about 700KB of code — MEANS something
    different after an edit to `X86.lean`. The currency check compared only the
    module's own bytes, so such an edit left `work.olean` in place and every
    later `lean` run silently recompiled the stale import inside the checker:
    measured, `python3 test_formal.py` went from 1.2 GB across 31 processes to a
    32 GB kill, with no error anywhere, because nothing was wrong with any
    single file — the artifact the checker read was simply not the artifact its
    source now describes. And the CAS key had the same hole, which is worse: a
    hit would have served that stale `.olean` to every machine.

    Transitive, and cycle-safe (`_seen`): `Contracts` imports `ProofLib` and
    `Refine`, `Refine` imports `ProofLib`, and a future cycle must not hang
    the build. One hash per module per run, so the whole library is a handful
    of 27MB reads rather than one per dependent."""
    import hashlib
    seen = set() if _seen is None else _seen
    if stem in seen:
        return ""
    seen.add(stem)
    path = os.path.join(lib_dir, stem + ".lean")
    if not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    deps = sorted(_module_imports(path))
    for dep in deps:
        h.update(dep.encode())
        h.update(_effective_digest(dep, lib_dir, seen).encode())
    return h.hexdigest()


def _acquire_build_lock(olean: str, timeout: float) -> int:
    """Exclusive, crash-safe lock for the build of ONE .olean.

    `flock`, not an O_EXCL lock file: the kernel drops the lock when the
    holder dies, so a process killed mid-build (a cancelled suite run, an
    OOM kill, Ctrl-C) cannot leave a lock file behind that wedges every
    later run forever. An O_EXCL marker would need a staleness heuristic to
    recover from exactly that, and a wrong staleness heuristic either hangs
    forever or lets two builds through.

    Returns the open fd; the caller releases with `_release_build_lock`.
    """
    import fcntl
    fd = os.open(olean + ".buildlock", os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() > deadline:
                os.close(fd)
                raise RuntimeError(
                    f"timed out after {timeout:.0f}s waiting for another "
                    f"process to build {os.path.basename(olean)}")
            time.sleep(0.25)


def _release_build_lock(fd: int) -> None:
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ── Vacuity: declarations whose statement asserts nothing ───────────────────
#
# The census of `sorry`s counts HOLES, and a hole is not the only way a proof
# can carry no information. `extern_<sym>_step : True := by trivial` — the step
# theorem at every extern call site, which is what the arm64 and x86-64
# generators emit for a `mojo_*` or libc call — is admitted by a complete proof
# and proves nothing whatsoever: `True` is inhabited, so the declaration is
# true whatever the machine model says about the call. It reports ZERO sorries
# and is exactly as uninformative as a `sorry`, and that is why a proof with a
# thousand of them and a proof with none of them are indistinguishable in the
# output.
#
# Why this is a TEXT scan and the sorry census is not — the asymmetry is the
# whole reason both exist, so it is worth stating exactly. Whether a `sorry`
# was ADMITTED depends on which tactic branch ran, which is elaboration; a grep
# counts the `all_goals first | … | sorry` alternatives that lost, so it is a
# count of hypothetical holes that never goes down (see `_run_lean`). Whether a
# declaration is VACUOUS is a property of its type ascription, and a type is a
# closed term: `theorem foo : True` is vacuous, is vacuous on every Lean
# version, and cannot be made non-vacuous by a tactic. So the same scan that is
# unsound for holes is the soundest possible instrument for this.
#
# Two shapes, and only two, because a count of everything that looks weak would
# be its own kind of untrustworthy number:
#
#   * the statement is literally `True` (parenthesised or not);
#   * the statement is `∀ …, … → True` — an implication to `True` under any
#     binder, which is inhabited for every argument, so a theorem of that shape
#     says nothing about the arguments either. `DylibExport.Semantics` in
#     lib/ProofLib.lean is this one, and it is what the dylib proofs'
#     `<export>_semantics` theorems are stated with.
#
# Both are reported with the declaration's NAME, because "3 vacuous" does not
# tell a reader where to look and "3 vacuous: extern_mojo_print_step,
# extern_malloc_step, …" does.
_VACUOUS_TRUE = "states `True`"
_VACUOUS_GOAL = "states `∀ …, … → True`"

# `(theorem|lemma|def) NAME` at the start of a line. The name is Lean's own
# component name, so dots and primes are part of it, and the leading `private`
# / `@[simp]` attributes are simply not matched — a declaration behind an
# attribute is still a declaration.
_DECL_RE = re.compile(r"^\s*(?:private\s+|protected\s+|noncomputable\s+)*"
                      r"(theorem|lemma|def)\s+([A-Za-z_][\w'.]*)")
# Lean 4 spells the dependent arrow `→` and `forall` as `∀`; ASCII `->` and
# `forall` are accepted so the scanner does not depend on a spelling choice.
# `\b` is wrong after `∀`: `∀` is not a word character in python's `re`, so
# `\b` there asks for a boundary between two non-word characters and never
# matches. The lookahead is the actual intent — a binder list follows.
_FORALL_RE = re.compile(r"^(?:∀|forall)(?=[\s(]).*(?:→|->)\s*True$", re.S)
_TRUE_RE = re.compile(r"^True$")


_OPEN = "([{"
_CLOSE = ")]}"


def _depth_delta(line: str) -> int:
    return sum(line.count(c) for c in _OPEN) - sum(line.count(c) for c in _CLOSE)


def _split_at_assignment(text: str):
    """(before, after) at the first `:=` at bracket depth 0, or (None, None).

    Lean cannot spell `:=` inside a type ascription, so bracket depth is the
    whole test. `None` means the header is not closed by anything on the text
    handed in — the caller's cue to read more lines or to give up, never to
    guess.
    """
    depth = 0
    for i, ch in enumerate(text):
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        elif ch == ":" and i + 1 < len(text) and text[i + 1] == "=" and depth == 0:
            return text[:i], text[i + 2:]
    return None, None


def _after_binders(text: str) -> str:
    """`text` with its leading binder groups removed, whitespace collapsed.

    A declaration's binders are `(x : Nat)`, `{α : Type}` and `[ι : Type]` groups
    in an unbroken run after the name, and everything after them is the return
    type (and, after the `:=`, the body). Consuming exactly that run is what
    keeps the parentheses in a RETURN type out of it: `theorem foo (x : Nat) :
    (P ∧ Q)` must be read as `P ∧ Q`, and a "last top-level `)`" rule reads it
    as empty instead.
    """
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1            # a binder RUN is separated by spaces or a newline
        if i >= n or text[i] not in _OPEN:
            break
        depth = 0
        while i < n:
            if text[i] in _OPEN:
                depth += 1
            elif text[i] in _CLOSE:
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
    return " ".join(text[i:].split())


def _unannotated(rest: str) -> str:
    """`rest` with the leading `:` that introduces the return type removed."""
    rest = rest.strip()
    return rest[1:].strip() if rest.startswith(":") else rest


def vacuous_declarations(text: str, body_lines: int = 8) -> list:
    """[(name, shape, line)] for declarations that assert nothing.

    `shape` is `_VACUOUS_TRUE` or `_VACUOUS_GOAL`, and is carried rather than
    counted because the two are different claims about a file: a `True`
    statement is a placeholder that was never filled in, while a `∀ …, … → True`
    is a TYPE somebody chose — a definition whose every inhabitant carries no
    information, which no proof of that definition can repair.

    A `def` is judged on its BODY and only when its declared return type is
    `Prop` (`DylibExport.Semantics … : Prop := ∀ observable, … → True` is the
    shape in this project). A `def` with no declared return type is skipped
    rather than inferred: Lean's inference is elaboration, and an inferred type
    is exactly the kind of judgement a text scanner has no business making.

    Every miss here is a miss, never a wrong answer, and that is the direction
    that matters — a scanner that reports a finding nobody can act on is the
    same defect as one that misses them.
    """
    lines = text.splitlines()
    out, head, head_line, kind, name, depth = [], None, 0, None, None, 0
    for lineno, raw in enumerate(lines, 1):
        if head is None:
            m = _DECL_RE.match(raw)
            if not m:
                continue
            kind, name, head, head_line, depth = m.group(1), m.group(2), [raw], lineno, 0
        else:
            head.append(raw)
        depth += _depth_delta(raw)
        before, after = _split_at_assignment("\n".join(head))
        if before is None:
            # The header has not closed. Read more — a statement is at most a
            # few lines and a BODY can be thousands, so this never scans one —
            # but do not read forever, and give up by starting afresh.
            if lineno - head_line > 12:
                head = None
            continue
        head = None
        # `before` still starts with `def NAME` / `theorem NAME`; the binder
        # skipper has to begin after the name or it stops on the first
        # character and returns the whole header as the statement.
        typed = _DECL_RE.sub("", before, count=1)
        if kind == "def":
            if _unannotated(_after_binders(typed)) != "Prop":
                continue                    # returns a value, not a proposition
            # A definition's proposition is its BODY, which continues onto the
            # following lines. It is bounded three ways — a blank line, a line
            # that starts another declaration, and the line cap — because
            # running on into the next declaration would leave `True` in the
            # middle of the text and make the whole match fail, which is how a
            # real finding goes missing to a sloppy terminator.
            stmt = " ".join(after.split())
            for extra in lines[lineno:lineno + body_lines]:
                if not extra.strip() or _DECL_RE.match(extra):
                    break
                stmt += " " + " ".join(extra.split())
        else:
            stmt = _unannotated(_after_binders(typed))
        # `after` is whatever followed the `:=` ON ITS OWN LINE, which is often
        # nothing at all with the body starting on the next line; the trim is
        # what keeps the whitespace a `" ".join` leaves behind from making
        # `^`-anchored patterns miss a real finding.
        stmt = stmt.strip()
        stmt = stmt.strip("()").strip() if stmt.startswith("(") else stmt
        if _TRUE_RE.match(stmt):
            out.append((name, _VACUOUS_TRUE, head_line))
        elif _FORALL_RE.match(stmt):
            out.append((name, _VACUOUS_GOAL, head_line))
    return out


# Lean's own hole report, which arrives on **STDOUT** (measured; see `_run_lean`).
# Two shapes, because the toolchain's wording is not something to depend on: the
# pinned 4.32.2 emits
#
#   lib/ProofLib.lean:4624:8: warning: declaration uses `sorry`
#
# — a LOCATION and no name — while some versions name the declaration. Both are
# matched, and a name that is absent is recovered from the line, which is
# strictly better than the location because it is what a reader has to open.
#
# This is also the measurement that was wrong the first time. Asking Lean to
# elaborate a module whose `.olean` was already current prints NOTHING — the
# artifact is a recovery cache, and a cached elaboration does not look at the
# holes — so a census taken that way reports a library with two `sorry`s in it
# as clean. That is why the real measurement copies the sources somewhere with
# no `.olean` beside them (see `library_census`), and why the record carries a
# tag saying which measurement produced it.
_SORRY_LOC_RE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s*warning:\s*"
    r"declaration uses\s+[`'\u2018]?sorry", re.M)
_SORRY_NAMED_RE = re.compile(r"declaration ['\u2018]([^'\u2019]+)['\u2019] uses")
_DECL_NAME_RE = re.compile(r"^\s*(?:private\s+|protected\s+|noncomputable\s+)*"
                           r"(?:theorem|lemma|def)\s+([A-Za-z_][\w'.]*)")

# The hole's OWN position, which `_SORRY_LOC_RE` above does not carry: that
# regex reads the `file:line:col` at the START of the warning, which is where
# the DECLARATION begins, so two holes in one declaration are the same location
# and one hole in a 3000-line theorem says nothing about which of its steps
# failed.
#
# Lean has had the answer in the warning itself since a labelled `sorry` went in
# (`Lean/Meta/Sorry.lean`: `mkLabeledSorry` builds a `SorryLabelView` carrying
# module, line, column and LSP range into the sorry's own type, "supporting
# pretty printing the sorry with an indication of source position when the
# option `pp.sorrySource` is true"). The option is the whole mechanism — with
# `set_option pp.sorrySource true` in the file, the warning becomes
#
#   /…/.tmp/tmpcmqrxbe0.lean:117:8: warning: declaration uses `sorry `«.tmp».tmpcmqrxbe0:363:12`
#
# and 363:12 is the `all_goals sorry` that fired, measured on this tree's own
# generated output (`formal/examples/const2.mojo`, one guard deliberately made
# unsatisfiable). Without the option the same run prints `declaration uses
# `sorry`` and there is nothing to parse, so a caller that wants positions has to
# ASK for them in the file it generates.
#
# **The label's module name is NOT delimited by the guillemets**, which is
# the shape a first reader would parse it by: the label is a `Name`, and Lean
# parenthesises only the component that is not a bare identifier, so a module
# under a directory prints as `«.tmp».tmpcmqrxbe0` — a balanced-looking pair
# around the WRONG part. What is unambiguous is that the position is the
# `:line:col` the message ENDS in, so that is what `_SORRY_LABEL_RE` below
# reads, and it captures no module at all.
#
# The trace option a project reaches for first — `trace.Meta.Tactic.sorryAx` —
# does not exist in the pinned 4.32.2 (`error: Unknown option`), which is why this
# is a reader of the warning rather than a probe: no second elaboration, no
# `run_cmd` block, no `import Lean.Elab.Command` in a generated file.

#: **There is no end-of-line anchor here, and that is the fix rather than a
#: simplification.** This used to end `\s*$`, and `$` under `re.M` matches at a
#: `\n` or at the very end of the string but NOT in the middle of a line — while
#: every caller concatenates the two streams (`p.stdout + p.stderr`), so a
#: warning that is the LAST line of stdout and arrives without its trailing
#: newline comes GLUED to the first line of a non-empty stderr and the anchor
#: fails on a message that is perfectly well formed. Measured on this tree's own
#: output: the patched `const2` proof's warning joined to a
#: `libc++abi: terminating…` line gives `[]` where the unjoined stdout gives
#: `[(363, 12)]`, so `_run_lean` reported "a hole fired and I cannot say where"
#: and `test_lean_says_which_sorry_fired_and_the_report_names_it` failed with
#: `None != "hstep7's side condition, line 363"` on an otherwise correct run.
#:
#: What replaces the anchor is `(?![0-9])`, and it is not the same claim: it says
#: the digits END there rather than that the LINE does. That distinction is the
#: point — the position is the `:line:col` the message ends in, so a `:363:12`
#: followed by a backtick, by a space, or by the next stream's first character is
#: all the same answer, while a `:363:129` must not read as `:363:12`. Measured:
#: `x:363:129` gives `[(363, 129)]`, and a warning with no label at all
#: (`declaration uses `sorry``) still gives `[]`, which is the answer that lets a
#: caller tell "no position" from "a position".
_SORRY_LABEL_RE = re.compile(
    r"declaration uses\s+[`'‘]?sorry\b[^\n]*?:(\d+):(\d+)(?![0-9])",
    re.M)


def sorry_source_positions(text: str) -> list:
    """`(line, col)` for each `declaration uses` warning that carries a position.

    Empty for a run whose file did not set `pp.sorrySource`, and that empty is
    the answer rather than a failure: Lean's warning still said the declaration
    uses `sorry`, so the hole is real and this only declines to say where. Callers
    read the emptiness instead of assuming a position, because a position invented
    from the declaration's own line is the wrong line more often than it is the
    right one.

    **One position per declaration, and it is the FIRST hole in it.** Lean emits
    the warning once per declaration — measured on a three-theorem control, where
    the declaration with two `sorry`s reported one — so this is the first live
    hole in a file and not the census of them.

    **A hole in an IMPORTED MODULE is not a position in this one, and this
    function cannot tell them apart.** The label carries a module name
    (`«lib».ProofLib`), and every caller throws that name away, so a warning
    about a `.olean` we merely imported arrives here looking exactly like one
    about the generated file — at the library's line, which is a line number in
    a DIFFERENT file. Measured on `formal/examples/const2.mojo`'s emitted text (722
    lines): a `«lib».X86:503:8` position resolves through `hole_at` to
    `"hstep11's side condition, line 503"`, a confident and wrong answer, while
    `«lib».ProofLib:4624:8` returns `None` only because 4624 is past the end of
    the generated file. Neither is the truth. `sorry_source_labels` is the reader
    that keeps the module; this one is the position-only reader its callers
    already have, and a caller that has the generated file's own module name to
    compare against should use that.
    """
    return [(int(m.group(1)), int(m.group(2)))
            for m in _SORRY_LABEL_RE.finditer(text or "")]


#: The SAME warning with its module name kept, as `(module, line, col)`. This is
#: the answer to "WHOSE hole", and it is separate from `sorry_source_positions`
#: rather than a replacement for it because the two answer different questions
#: and only one of them can be answered by the digits: a position without its
#: module cannot be attributed to a file, which is the whole of the
#: misattribution `sorry_source_positions`' own docstring names.
#: The label as a whole — everything between the backtick that opens it and the
#: `:line:col` that closes it — so that a module spelled with guillemets and one
#: spelled bare are BOTH captured by one pattern rather than by two. Guillemet
#: position is not the thing being read (see the note above): this keeps the
#: label intact and `sorry_source_labels` takes the LAST dotted component, which
#: is the one that names the file in either spelling.
_SORRY_LABEL_TEXT_RE = re.compile(
    r"declaration uses\s+[`'‘]?sorry\s+[`'‘]([^\n]*?)[»'’]?"
    r":(\d+):(\d+)(?![0-9])",
    re.M)


def sorry_source_labels(text: str) -> list:
    """`(module, line, col)` per `declaration uses` warning, module INCLUDED.

    The module is what says the hole is in a file the caller generated rather
    than in an `.olean` it imported, and that is a question no amount of reading
    the digits can answer: `«lib».ProofLib:4624:8` and `<tmp>.lean:4624:8` are the
    same three numbers and completely different facts.

    **`module` is the LAST component of the label, and that is what identifies
    the file.** Lean's own spelling is the awkward one this has to survive: the
    guillemets wrap the component that is not a bare identifier, so a module
    under a directory prints as `«.tmp».tmpcmqrxbe0` — the pair sits around the
    WRONG part — and a top-level module prints with no guillemets at all. Reading
    the last component of the dotted name gives `tmpcmqrxbe0` and `topmod`
    respectively, which is the basename of the file in both cases, so a caller
    can compare it against the file it generated. Measured on the three shapes
    Lean actually emits on this tree:

        «.tmp».tmpcmqrxbe0:363:12   ->  ('tmpcmqrxbe0', 363, 12)
        «lib».ProofLib:4624:8        ->  ('ProofLib', 4624, 8)
        topmod:10:2                  ->  ('topmod', 10, 2)

    A warning with NO label — `declaration uses `sorry``, i.e. a file that did not
    set `pp.sorrySource` — is absent from this list rather than present with an
    empty module, because there is no position to attach a module to. That is the
    distinction `sorry_source_positions` reports as `[]`, and a caller that has
    both readers can say "a hole fired and I know whose file it is in" against "a
    hole fired and I know nothing", which are different reports.
    """
    out = []
    for m in _SORRY_LABEL_TEXT_RE.finditer(text or ""):
        label = m.group(1).replace("«", "").replace("»", "").strip()
        out.append((label.rsplit(".", 1)[-1], int(m.group(2)),
                    int(m.group(3))))
    return out



def _declaration_at(lines, lineno: int) -> str:
    """The declaration a warning at `lineno` belongs to, or `line N`.

    Lean reports a hole's position inside the declaration, so the name is the
    nearest `theorem`/`lemma`/`def` header at or above that line. Falling back to
    the LINE is deliberate: an unnamed entry is still a location a reader can
    act on, whereas a wrong name is worse than none.

    A line outside the source is the case that makes the fallback necessary
    rather than cosmetic. Clamping the index instead — which is what the first
    version did — silently attributes every out-of-range hole to the LAST
    declaration in the file, and two holes then de-duplicate to one and the
    count comes back short. A count that is short because a name collided is
    indistinguishable, in the output, from a count that is right.
    """
    if lineno < 1 or lineno > len(lines):
        return f"line {lineno}"
    for i in range(lineno - 1, -1, -1):
        m = _DECL_NAME_RE.match(lines[i])
        if m:
            return m.group(1)
    return f"line {lineno}"


def _census_from_output(text: str, source_lines=None) -> tuple:
    """(n, (names...)) from one `lean` run's output, de-duplicated in order.

    `source_lines` is the module's lines, and it is what turns Lean's anonymous
    "declaration uses sorry" into a name — see `_declaration_at`. Without it
    the names are the locations, which is still actionable and never wrong.
    """
    text = text or ""
    hits = list(_SORRY_LOC_RE.finditer(text))
    named = _SORRY_NAMED_RE.findall(text)
    names, seen = [], set()
    for i, m in enumerate(hits):
        if i < len(named):
            name = named[i]
        elif source_lines is not None:
            name = _declaration_at(source_lines, int(m.group("line")))
        else:
            name = f"{m.group('file')}:{m.group('line')}"
        if name not in seen:
            seen.add(name)
            names.append(name)
    if not hits and named:
        # A wording that names the declaration without the `warning:` prefix the
        # pinned toolchain uses. Counted, because a hole is a hole.
        for name in named:
            if name not in seen:
                seen.add(name)
                names.append(name)
    return len(names), tuple(names)


# The census record is VERSIONED inside its own value, not only in its key.
# That is not belt-and-braces: the first version of this measurement asked Lean
# to elaborate a module whose `.olean` was already current, Lean served it from
# that cache and printed nothing, and the result was published as "0 holes" for
# every module in `lib/`. A wrong number in a content-addressed store is
# permanent — every later reader gets it — and it is exactly the number this
# exists to make trustworthy, so the record has to be able to say which
# measurement produced it. A body without this tag is a MISS, which is the only
# safe reading of a value written by a version that measured nothing.
_CENSUS_TAG = "lean-lib-census-v3"


def _census_lookup(key: str):
    """The census recorded beside a library .olean, or None if never measured."""
    import cas
    hit = cas.lookup(key, CENSUS_EXT)
    if not hit:
        return None
    try:
        with open(hit, "rb") as f:
            body = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    tag, _, rest = body.partition("\n")
    if tag != _CENSUS_TAG:
        return None
    head, _, names = rest.partition("\n")
    try:
        count = int(head)
    except ValueError:
        return None
    return count, tuple(n for n in names.split("\t") if n)


def _census_publish(key: str, census: tuple) -> None:
    import cas
    try:
        cas.publish(key, CENSUS_EXT,
                    (_CENSUS_TAG + "\n" + str(census[0]) + "\n"
                     + "\t".join(census[1])).encode())
    except OSError:
        pass          # a census that cannot be stored must not fail a build


def library_census(lean: str, lib_dir: str, timeout: int | None = None,
                   measure: bool = True, cpu_s: float | None = None) -> dict:
    """stem -> (n_sorries, (names...)) for every library module MEASURED.

    `timeout` is the launcher's WALL bound (default `library_bounds()[0]`, which
    is also the only bound an environment may raise) and, unchanged, how long
    this waits for a peer's build lock. Those are two different facts sharing
    one argument; they were one argument before this module had a policy, and
    keeping them together is cheaper than changing a signature four callers in
    two other workers' files depend on. Both mean "how long may this take".

    The hole census of a generated proof is not the whole story, and the gap
    was silent: a proof file is elaborated by `lean`, and Lean warns about
    every `sorry` it admits IN THAT FILE — but `lib/ProofLib.lean` and
    `lib/Refine.lean` are consumed as pre-built `.olean`s, so a `sorry` in
    them produces no warning at all when the proof imports them. That is not
    a small hole: `Refine.dylib_export_contract_stub` is a bare `sorry` and is
    what every `dylib --formal` proof's contract theorem rests on, and
    `test_formal_dylib.py`'s "the generated proof contains no sorry" check
    greps the GENERATED file, so it is green.

    So the census has to reach the library too, and the only sound way to count
    a hole is to elaborate the module and read what Lean says.

    **And here is the part that was hiding them, measured rather than guessed.
    Elaborating a module whose `.olean` is already present and current prints
    NOTHING**: Lean uses the existing artifact as a recovery cache and skips
    elaboration entirely, so the run that "measures" `lib/ProofLib.lean` on a
    tree that has been built once reports zero holes for a file with two. That
    was the mechanism, and it is the same mechanism that made the holes
    invisible to every consumer: the `.olean` is a cache, and a cached
    elaboration is precisely the one that does not look at the holes. The first
    version of this function got it wrong in exactly that way and reported all
    four library modules clean.

    So the measurement is made where no cache can hide: the sources are copied
    into a private temp directory, which therefore has no `.olean` beside them,
    and elaborated there with `LEAN_PATH` pointing at the copy FIRST and the
    real `lib/` second — so a module's own dependencies come from the copy as
    they are produced, and a module that is only in `lib/` still resolves.
    Nothing in `lib/` is written, and nothing here is published as a `.olean`,
    because an artifact built from a copied source is not the artifact
    `ensure_library` would produce and must not be served as one.

    The cost is one full elaboration per module — the same ~90s that building
    the `.olean` costs, paid once, then cached in the CAS under the `.olean`'s
    own key so a cas hit on the artifact is a hit on its census. The per-`.olean`
    flock is taken, and the CAS re-checked inside it, so concurrent callers
    still produce one measurement between them.

    **A module that cannot be measured is ABSENT from the returned dict, never
    present with a zero.** Those are different facts and conflating them is how
    "the library has no holes" gets reported by a tool that never looked. The
    report says which of the two it is printing.
    """
    out, missing = {}, []
    if timeout is None:
        timeout, lib_cpu = library_bounds()
    else:
        lib_cpu = cpu_s if cpu_s is not None else library_bounds()[1]
    for stem in LIBRARY_MODULES:
        source = os.path.join(lib_dir, stem + ".lean")
        if not os.path.isfile(source):
            continue
        if stem in _LIB_CENSUS:
            out[stem] = _LIB_CENSUS[stem]
            continue
        try:
            key = _olean_key(stem, source, lean, _effective_digest(stem,
                                                                   lib_dir))
        except Exception:
            # An unreadable source or a broken store means UNMEASURED, which
            # the caller reports as such. It must not be an exception: this is
            # a report about a proof, not a gate on one.
            missing.append(stem)
            continue
        got = _census_lookup(key)
        if got is None:
            missing.append(stem)
        else:
            out[stem] = got
    if not missing or not measure:
        return out
    olean = os.path.join(lib_dir, missing[0] + ".olean")
    fd = _acquire_build_lock(olean, timeout)
    try:
        still = {}
        for stem in missing:
            source = os.path.join(lib_dir, stem + ".lean")
            try:
                got = _census_lookup(_olean_key(
                    stem, source, lean, _effective_digest(stem, lib_dir)))
            except Exception:
                got = None
            if got is not None:
                still[stem] = got          # a peer may have measured it
        out.update(still)
        todo = [s for s in missing if s not in still]
        if not todo:
            return out
        with tempfile.TemporaryDirectory(prefix="lean_census_") as td:
            for stem in LIBRARY_MODULES:
                src = os.path.join(lib_dir, stem + ".lean")
                if os.path.isfile(src):
                    shutil.copyfile(src, os.path.join(td, stem + ".lean"))
            env = os.environ.copy()
            # The COPY FIRST, so a dependency that is itself being measured is
            # found as the `.olean` this run just produced rather than as the
            # cached one it was supposed to be standing in for.
            #
            # ABSOLUTE, and that is not tidiness: `LEAN_PATH` is resolved
            # against the elaborating process's own cwd, which is the temp
            # directory, so a relative `lib` handed in by a caller points at
            # `<tempdir>/lib` and every import of another library module fails.
            # The first version of this took `lib_dir` as given, measured
            # ProofLib from the CAS, then reported X86/work/Refine as
            # UNMEASURED — a third silent way for the census to shrink to
            # whatever happened to be cached.
            env["LEAN_PATH"] = os.pathsep.join((td, os.path.abspath(lib_dir)))
            for stem in todo:
                src = os.path.join(td, stem + ".lean")
                if not os.path.isfile(src):
                    continue
                got = _measure_one(lean, src, td, env, timeout,
                                   _read_lines(src), lib_cpu)
                if got is None:
                    continue               # unmeasured, and said as such
                _LIB_CENSUS[stem] = got
                out[stem] = got
                try:
                    _census_publish(_olean_key(
                        stem, os.path.join(lib_dir, stem + ".lean"), lean,
                        _effective_digest(stem, lib_dir)), got)
                except Exception:
                    pass
    finally:
        _release_build_lock(fd)
    return out


# ── `#print axioms`: what a declaration's TRANSITIVE closure rests on ────────
#
# `_census_from_output` above reads Lean's hole report.  This reads the other
# one, and it is here because there is no text scan for what it measures:
# `formal/admitted.py::library_trust` counts the `native_decide`/`bv_decide`
# SITES in a module, which is what the source says, and `#print axioms` measures
# what the PROOF TERM actually closes over.  The two differ in three ways that
# matter, and all three have bitten somebody:
#
#   * it is transitive, so a theorem with no tactic site of its own still reports
#     every axiom its callees' proofs used;
#   * a tactic site that never ran — a losing branch of `first | … | …` — leaves
#     no axiom, so the site count can be an over-count;
#   * and the axiom is NOT named `Lean.ofReduceBool` on the pinned 4.32.2.
#     `ofReduceBool` is deprecated there ("in-kernel native reduction is
#     deprecated; assert native evaluations with axioms instead"), and the
#     `native_decide` TACTIC elaborates to a FRESH AXIOM PER USE, named after
#     the declaration that used it:
#     `work_step_mov._native.native_decide.ax_1_1`.  A census that greps for
#     `ofReduceBool` therefore reports CLEAN over a library that is not.
#
# `AXIOM_FOUNDATION` is the part of the answer that is Lean's own and not this
# tree's: `propext`, `Quot.sound` and `Classical.choice` are what every
# `simp`/`decide` proof in Lean rests on, so they are named rather than
# tolerated — a caller comparing against them is comparing against a list, and
# a list can be wrong.
_AXIOM_DEPENDS_RE = re.compile(
    r"^'(?P<name>[^'\n]+)' depends on axioms:\s*\[(?P<body>[^\]]*)\]", re.M)
_AXIOM_NONE_RE = re.compile(
    r"^'(?P<name>[^'\n]+)' does not depend on any axioms", re.M)
AXIOM_FOUNDATION = frozenset({"propext", "Quot.sound", "Classical.choice"})
# A per-use axiom the reflection tactics create, whatever the toolchain calls
# it: `<declaration>._native.<tactic>.ax_<n>_<m>`.  Matched structurally
# because the index after `ax` is the toolchain's business and changed once
# already in the direction that matters (ONE counter for the whole module, so
# deleting one site's axiom renumbers every later one in the file — which is why
# no test may pin an index).  The declaration group is GREEDY: a namespaced
# declaration's axiom is `DylibExport.backward_branch_run_none._native.…` and a
# lazy `.+` would hand `DylibExport` to `decl` and fail to match at all.
#: Lean's OWN memory ceiling, in its own words on the pinned toolchain, and the
#: second shape the same ceiling takes when it fires from a different place.
#: **This lives here and not in a caller because this module is what SETS the
#: ceiling** (`lean_flags`'s `-M LEAN_MEMORY_MB`), so it is the only layer that
#: can say both halves of the claim: that the sentence is a bound firing and that
#: the bound is ours. Two readers of one sentence is how a reworded ceiling ends
#: up classified as a proof failure by one tool and as an absence by another —
#: and that disagreement is exactly what
#: `bugs/FORMAL_eighteen_examples_have_no_accepted_proof_and_seven_are_declared.md`
#: records for `both` and `either`, the two examples whose proof Lean's `-M`
#: refuses rather than rejects.
LEAN_MEMORY_REFUSAL_RE = re.compile(
    r"excessive memory consumption detected|maximum memory has been reached")


def lean_refused_on_its_own_memory_ceiling(text: str) -> str | None:
    """The line on which Lean hit ITS OWN memory ceiling, or None.

    **A ceiling firing is not a verdict on the proof, and the two must not be
    counted as one.** `formal/lean.py`'s own comment on `LEAN_MEMORY_MB` says
    why: the project's 4 GB line cannot be enforced by capping Lean, and
    raising the cap is not tightening a policy, it is letting the work through —
    so at some size a proof stops being CHECKED and the only true sentence is
    "the checker ran out". A caller that files that as `lean-rejected` reports a
    proof that may be fine as one Lean could not decide, and a caller that files
    it as a pass has swapped one lie for another.

    Matched on the RUN'S output rather than on `compile_formal`'s exception text,
    because the run is the thing that said it, and a replayed verdict's stored
    detail is that sentence followed by the diagnostics — so an anchored pattern
    would find the header and produce a different string from the same failure
    on the two paths.

    The LINE is returned rather than a boolean, so a caller can print what Lean
    said instead of paraphrasing it: the two forms are
    `…:8: error: (kernel) excessive memory consumption detected` and
    `maximum memory has been reached`, and a reader who has to guess which one
    fired cannot tell a kernel allocation from an elaboration budget.
    """
    for line in (text or "").splitlines():
        if LEAN_MEMORY_REFUSAL_RE.search(line):
            return line.strip()
    return None


GENERATED_AXIOM_RE = re.compile(
    r"^(?P<decl>.+)\._native\.(?P<tactic>[A-Za-z_]\w*)\.ax_\d+_\d+$")


def parse_axioms(output: str) -> dict:
    """`{declaration: (axioms…)}` out of one `lean` run's `#print axioms` output.

    A declaration that reported nothing is ABSENT from the result rather than
    mapped to an empty tuple, and the difference is the whole reason a caller
    has to check: an absent name is one Lean could not find (an `Unknown
    constant` error, which is a disagreement between the census and the
    library) and an empty tuple is a declaration that genuinely rests on
    nothing.  Reporting both as `()` would make a renamed declaration look like
    a clean one.
    """
    out = {}
    for m in _AXIOM_NONE_RE.finditer(output or ""):
        out[m.group("name")] = ()
    for m in _AXIOM_DEPENDS_RE.finditer(output or ""):
        out[m.group("name")] = tuple(
            a.strip() for a in m.group("body").split(",") if a.strip())
    return out


def print_axioms(lean: str, lib_dir: str, imports, names,
                 wall_s: float | None = None, cpu_s: float | None = None,
                 mem_mb: int | None = None) -> tuple:
    """`(LeanRun, {declaration: (axioms…)})` for `names`, through `run_lean`.

    `imports` is a module name or a list of them; `names` are the declarations
    to ask about, spelled the way a `#print axioms` line spells them — which is
    QUALIFIED, so `DylibExport.backward_branch_run_none` and not the bare name
    `formal/admitted.py::_declarations` returns for the unqualified spelling.

    One run for all of them, because each is a separate `lean` process paying
    the whole 30 MB `ProofLib.olean` load and the answer is microseconds of
    work: asking 513 declarations costs one process instead of 513.

    The generated file goes to `scratch_dir` and is handed to `lean` as an
    ABSOLUTE path, for the reason that function's docstring gives — a shared
    fixed name is a hazard `tools/suite.py -j 18` turns into someone else's
    failure.
    """
    if isinstance(imports, str):
        imports = [imports]
    names = list(names)
    if not lean:
        return (LeanRun(None, "", "", "lean not found (see ./lean-toolchain)",
                        0.0, 0.0, 0, 0), {})
    env = os.environ.copy()
    env["LEAN_PATH"] = os.pathsep.join((os.path.abspath(lib_dir),
                                        env.get("LEAN_PATH", "")))
    with scratch_dir("print-axioms") as td:
        source = os.path.join(td, "axioms.lean")
        with open(source, "w", encoding="utf-8") as f:
            # ONE `import` per module: `import A B C` is not Lean.  It reads as if
            # it were and it is not — the pinned parser reads the module name and
            # then finds `Refine` where a command was expected — so a multi-module
            # `import` line leaves every module after the FIRST one unimported and
            # every declaration in it an `Unknown constant`.  Measured here: 230 of
            # 513 declarations "missing" for exactly that reason, which is the
            # shape of a wholesale failure that a check keyed on "did anything
            # come back" would have passed.
            for m in imports:
                f.write(f"import {m}\n")
            for n in names:
                f.write(f"#print axioms {n}\n")
        run = run_lean(lean, [source], env=env, wall_s=wall_s, cpu_s=cpu_s,
                       mem_mb=mem_mb)
        return run, parse_axioms(run.stdout)


def _measure_one(lean: str, source: str, workdir: str, env: dict,
                 timeout: int, source_lines=None, cpu_s: float | None = None):
    """The hole census of one module, or None if it could not be measured.

    None and `(0, ())` are kept apart all the way to the report. Lean exits
    non-zero on a module with an ERROR, and a module with errors also has no
    trustworthy census, so a non-zero exit is unmeasured rather than a count —
    the only thing a failed elaboration can honestly report about holes is
    nothing.

    A run that broke one of the launcher's bounds is unmeasured for the same
    reason, and says so: the elaborator was killed part-way through the file, so
    whatever warnings it had already printed are a prefix of the answer, not the
    answer.  The partial output goes to stderr anyway, because a run that hit a
    bound is a thing a reader has to be able to find in a log.
    """
    # The `.olean` is LEFT in place. It is the artifact a later module in the
    # same run imports, and deleting it after each measurement (the first
    # version did) means every module after the first is elaborated against the
    # cached library instead of the copy — which is a weaker claim than "this
    # measurement stands on nothing but the sources", and silently so. The
    # caller's TemporaryDirectory removes the whole set.
    out = os.path.join(workdir, os.path.basename(source)[:-5] + ".olean")
    res = run_lean(lean, ["-o", out, source], cwd=workdir, env=env,
                   wall_s=timeout, cpu_s=cpu_s, mem_mb=LIBRARY_MEMORY_MB)
    if res.exceeded:
        print(f"  [lean census: {os.path.basename(source)}: {res.exceeded}]",
              file=sys.stderr)
        return None
    if res.returncode != 0:
        return None
    return _census_from_output((res.stderr or "") + (res.stdout or ""),
                               source_lines)


def _read_lines(path: str):
    """A file's lines, or None if it cannot be read.

    None is not an empty list on purpose: it means "cannot resolve a hole's
    line to a declaration", which downgrades the census to locations. An empty
    list would make every line resolve to `line 1`.
    """
    try:
        with open(path, "r", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return None


def ensure_library(lean: str, lib_dir: str, timeout: int | None = None,
                   cpu_s: float | None = None) -> None:
    """Make every library .olean current, building at most ONE of each.

    `timeout`/`cpu_s` are the launcher's bounds for the build itself and default
    to `library_bounds()` — the one bound in this module an environment may
    raise, because this is the one step whose cost cannot be bounded in advance
    (it is a function of how large `lib/*.lean` has grown, and it is already an
    order of magnitude slower than any proof). `timeout` is also, unchanged, how
    long this waits for a peer's build lock.

    The check-build step is a check-then-act on a shared filesystem, and the
    proof suite runs ~16 of these concurrently, so without the lock below
    every one of them misses the stamp at the same instant, misses the cas
    on a cold store, and starts its own `lean -o <same path>` — N
    simultaneous ~80s builds of a 27MB artifact, all writing the SAME output
    file. Measured on a cold cas with 3 concurrent callers: 3 builds, peak 3
    concurrent `lean`, all finishing at ~81s. That is a correctness hazard
    as much as a waste — concurrent unsynchronised writes to one output path
    can interleave into a truncated or mixed .olean, and every later
    typecheck then reads it.

    Two things fix it, and both are here: the build happens under an
    exclusive lock with the currency check REPEATED inside it (a peer may
    have built it while we queued), and the build writes to a private temp
    path that is `os.replace`d into place, so even a lock that did not hold
    could not leave a partial file where a valid one belongs.

    This makes concurrent callers cheap but does not make them FREE: the
    lock is per-.olean and serialised, so 16 processes still queue. The
    suite therefore also registers the library build as its own test
    (`prooflib` in tools/suite.py) and every proof-checking test depends on
    it, so the one build happens once, alone, before the fan-out starts and
    the other 15 find the stamp valid and return immediately.
    """
    import cas
    if timeout is None:
        timeout, build_cpu = library_bounds()
    else:
        build_cpu = cpu_s if cpu_s is not None else library_bounds()[1]
    env = os.environ.copy()
    env["LEAN_PATH"] = lib_dir
    for stem in LIBRARY_MODULES:
        source = os.path.join(lib_dir, stem + ".lean")
        olean = os.path.join(lib_dir, stem + ".olean")
        stamp = olean + ".srcsha256"
        if not os.path.isfile(source):
            continue
        digest = _effective_digest(stem, lib_dir)
        if _library_is_current(source, olean, stamp, digest):
            continue
        # Pre-stamp trees (fresh clone, or an olean built by the Makefile):
        # accept it if it is newer than the source, then record its digests so
        # later touches are free. Stamp-only, so no lock needed — and
        # _write_stamp is itself atomic.
        if (not os.path.isfile(stamp) and os.path.isfile(olean)
                and os.path.getmtime(olean) >= os.path.getmtime(source)):
            _write_stamp(stamp, source, olean, digest)
            continue
        key = _olean_key(stem, source, lean, digest)
        fd = _acquire_build_lock(olean, timeout)
        try:
            # DOUBLE-CHECK under the lock. Everyone else in the fan-out is
            # doing the same thing, and the whole point of the lock is that
            # exactly one of them proceeds past here.
            if _library_is_current(source, olean, stamp, digest):
                continue
            hit = cas.lookup(key, ".olean")
            if hit:
                shutil.copyfile(hit, olean)
            else:
                tmp = f"{olean}.tmp.{os.getpid()}"
                try:
                    result = run_lean(lean, ["-o", tmp, source], env=env,
                                      wall_s=timeout, cpu_s=build_cpu,
                                      mem_mb=LIBRARY_MEMORY_MB)
                    if result.exceeded:
                        # Raised, not returned: a build that broke a bound left
                        # no .olean, and every later caller would otherwise take
                        # the "lean failed" path and report it as a build error
                        # instead of as the thing it is.
                        raise RuntimeError(result.exceeded)
                    if result.returncode != 0:
                        raise RuntimeError((result.stderr or result.stdout
                                            or "lean failed").strip())
                    os.replace(tmp, olean)
                finally:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                with open(olean, "rb") as f:
                    cas.publish(key, ".olean", f.read())
                # The run that just elaborated this module is the only place
                # Lean ever reports the holes IN it — a later proof consumes
                # the .olean and is told nothing. Captured here it costs
                # nothing, because the elaboration was going to happen anyway;
                # `library_census` is the reader, and a pre-built .olean has no
                # such moment, which is the one case it measures for itself.
                got = _census_from_output(
                    (result.stderr or "") + (result.stdout or ""),
                    _read_lines(source))
                _LIB_CENSUS[stem] = got
                _census_publish(key, got)
            _write_stamp(stamp, source, olean, digest)
        finally:
            _release_build_lock(fd)


# ── verdict cache ───────────────────────────────────────────────────────────
#
# Typechecking a generated proof is the dominant cost of the whole formal
# pipeline: these proofs are ~700KB of `native_decide` goals and take tens of
# seconds of wall time and *more* system time than user time (the 27MB
# ProofLib.olean is mapped and the native_decide shared objects are loaded per
# goal). The verdict, though, is a pure function of its inputs, so it caches
# like any other compile artifact — in cas.py's content-addressed store, which
# is exactly the tier-1 "instantiate once, ever" mechanism
# (MODULE_CACHE_DESIGN.md). Re-running `make check-formal`, or rebuilding the
# same dylib twice, then costs a hash instead of a Lean run.
#
# The key folds in everything that can change the verdict, and nothing else:
#   * the proof file's exact bytes — the complete source lean reads;
#   * every .olean reachable through LEAN_PATH (ProofLib/work/Refine), by
#     content: rebuilding an .olean from unchanged source can still change its
#     bytes, and a changed import is exactly what a stale verdict must not
#     survive;
#   * the lean binary's `--version`, so a toolchain bump (or switching from
#     the pinned toolchain to another one) invalidates every verdict.
# The proof's own directory is deliberately NOT in the key: the generator only
# ever emits `import ProofLib/work/Refine`, so the verdict does not depend on
# where the file happens to sit, and keying on the path would make a cache
# that misses for a file merely copied somewhere else.

def _digest(path: str) -> bytes:
    """sha256 of a file's bytes, memoised on (size, mtime_ns) so a suite of
    concurrent runs hashes ProofLib.olean (27MB) once, not once per proof."""
    st = os.stat(path)
    memo_key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    hit = _OLEAN_DIGESTS.get(memo_key)
    if hit is not None:
        return hit
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    value = h.digest()
    _OLEAN_DIGESTS[memo_key] = value
    return value


_LEAN_VERSIONS: dict = {}


def lean_version(lean: str, timeout: float = 120.0) -> str:
    """The toolchain's own `--version` string, or "unknown".

    Through the launcher like everything else, with a bound this short because
    the run is `lean --version`: it prints a line and exits.  That is not an
    excuse for no bound — a `lean` that cannot print its version is a `lean` that
    hangs before `main`, and the first version of this had no bound at all.

    The verdict this string feeds is a CAS KEY, so "unknown" is a real answer
    here and not a shrug: it is a key no other machine produces, which is what
    makes a run under an unusable toolchain a MISS rather than a collision.

    Memoised on the binary's (size, mtime), because this is on the path of every
    `_olean_key` and every `proof_verdict_key` — five modules and a proof per
    `ensure_library` — and re-running it per key meant re-spawning `lean` (and,
    since the launcher arrived, re-reading `ps`) for a string that cannot have
    changed within one process.  Keyed on the binary's identity rather than its
    path alone so a toolchain swapped underneath a long run is still re-read.
    """
    try:
        st = os.stat(lean)
        key = (lean, st.st_size, st.st_mtime_ns)
    except OSError:
        key = (lean, None, None)
    hit = _LEAN_VERSIONS.get(key)
    if hit is not None:
        return hit
    res = run_lean(lean, ["--version"], wall_s=timeout, cpu_s=timeout)
    got = "unknown" if (res.exceeded or res.returncode != 0) else \
        (res.stdout or res.stderr or "").strip()
    _LEAN_VERSIONS[key] = got
    return got



# v3 added the library census (`lib_sorries`, `lib_detail`) to the stored body,
# so the key changes rather than a v2 entry being read as "the library has no
# holes" — which is exactly the claim v2 could not make and did not check.
#
# v4 is the same argument about a fact the key never recorded at all: whether
# the run FOUND the library. `_run_lean` handed `LEAN_PATH` the `lib_dir` it was
# given, unresolved, while the process's cwd is the proof's own directory — so a
# caller passing a relative `repo_root` (and `repo_root="."` is what a bug doc's
# own reproduce command writes) got `error: unknown module prefix 'ProofLib'` at
# `1:0`, before the theorem is read, and **that false verdict was published and
# is content-addressed on inputs that do not change when the path is fixed**:
# the proof's bytes and the library's `.olean` digests are identical either way,
# so every later caller with the same file replayed it. `bugs/
# FORMAL_eval_eq_mojo_is_undecidable_over_a_free_n.md`'s measurements were taken
# through that entry point, which is why this bump and not a cache flush: a
# flush cannot be done from a worktree (the CAS is machine-wide and shared), and
# a version bump retires exactly the entries whose key cannot tell the two runs
# apart.
_VERDICT_VERSION = b"formal-proof-verdict-v4"
# -1 in the `lib_sorries` field, distinct from 0: "not measured" and "measured,
# no holes" are different facts and the report prints them differently.
_LIB_UNMEASURED = -1


def proof_verdict_key(proof_path: str, lib_dir: str, lean: str) -> str:
    import cas
    parts = [_VERDICT_VERSION, lean_version(lean).encode()]
    for stem in LIBRARY_MODULES:
        parts.append(stem.encode())
        olean = os.path.join(lib_dir, stem + ".olean")
        parts.append(_digest(olean) if os.path.isfile(olean) else b"\0missing")
    with open(proof_path, "rb") as f:
        parts.append(f.read())
    return "proof/" + cas.hash_parts(*parts)


# What a proof check actually established. `ok` is the verdict every existing
# caller reads and the only one that gates anything; the rest is the census,
# and it exists because `ok` on its own is a claim this project has made and
# cannot support. A proof that admits a thousand `sorry`s passes; so does one
# whose only step theorems are `True := by trivial`; so does one that rests on a
# `sorry` in a `.olean` Lean never re-reports. `lines` is the human-readable
# form, and `check_proof_cached` writes it to stderr on every call, so the
# figure cannot be computed and then dropped on the floor again — which is
# precisely what it was for a year.
Census = collections.namedtuple(
    "Census", "ok detail cached n_sorries lib_sorries lib_detail lines")


def proof_census(proof_path: str, repo_root: str | None = None,
                 timeout: float | None = None, cpu_s: float | None = None) -> Census:
    """`(ok, detail, cached, n_sorries, lib_sorries, lib_detail, lines)`.

    `check_proof_cached` is this with the census rendered; it exists separately
    so a caller that wants to REPORT the census (fire.py's `Proof:` line, this
    repository's own test) does not have to re-derive it, and so the four
    elements the older signature returns keep meaning exactly what they meant.

    **Report, not gate.** Nothing in here changes `ok`, and nothing here raises:
    a census that cannot be measured is printed as unmeasured, never as zero.
    That is deliberate and it is the reason this can land in the middle of four
    other agents' work without changing a verdict anyone is relying on.

    `timeout`/`cpu_s` are the launcher's bounds for the PROOF check and default
    to `PROOF_WALL_S`/`PROOF_CPU_S`; the library build it depends on uses its own
    (`library_bounds()`), because the two are different work with different
    honest costs. Under its old name `timeout` means wall seconds, which is what
    it meant before the launcher existed and what every caller passed.
    """
    root = repo_root or _default_root()
    lib_dir = os.path.join(root, "lib")
    lean = find_lean(root)
    wall_s = PROOF_WALL_S if timeout is None else float(timeout)

    def census(ok, detail, cached, n_sorries, lib):
        lines = _census_lines(proof_path, lib_dir, n_sorries, lib)
        lib_sorries, lib_detail = _lib_totals(lib)
        return Census(ok, detail, cached, n_sorries, lib_sorries, lib_detail,
                      lines)

    if not lean:
        return census(False, "lean not found", False, 0, {})
    try:
        ensure_library(lean, lib_dir)
    except Exception as e:
        return census(False, f"proof library build failed: {e}", False, 0, {})
    try:
        key = proof_verdict_key(proof_path, lib_dir, lean)
    except OSError as e:
        return census(False, f"proof file unreadable: {e}", False, 0, {})
    # Measured AFTER the library is current and BEFORE the verdict is read, so
    # the stored body and this run's figures cannot disagree. A failure here is
    # swallowed on purpose: the census is a report, and a report that cannot be
    # produced must not turn a passing proof into a failing one.
    try:
        lib = library_census(lean, lib_dir)
    except Exception:
        lib = {}
    stored = cas_lookup_verdict(key)
    if stored is not None:
        ok, n_sorries, lib_sorries, lib_detail, detail = stored
        lib = _lib_from_record(lib, lib_sorries, lib_detail)
        return census(ok, detail, True, n_sorries, lib)
    ok, detail, n_sorries, exceeded = _run_lean(proof_path, lib_dir, lean,
                                                wall_s, cpu_s)
    lib_sorries, lib_detail = _lib_totals(lib)
    if not exceeded:
        _publish_verdict(key, ok, n_sorries, lib_sorries, lib_detail, detail)
        return census(ok, detail, False, n_sorries, lib)
    # A BREACH IS NOT A VERDICT, and the difference is worth a branch. What the
    # CAS stores is a pure function of the proof's bytes and the toolchain; a
    # bound is a function of the MACHINE (how loaded, how many proofs at once),
    # so caching it turns one slow afternoon into a permanent red that no
    # re-run can clear — which is exactly what
    # `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` records about a cached
    # timeout. So a breach is reported, never published, and its hole census is
    # UNMEASURED rather than the partial prefix the killed run managed to print.
    return census(False, detail, False, None, lib)


def cas_lookup_verdict(key: str):
    """`(ok, n_sorries, lib_sorries, lib_detail, detail)` from the CAS, or None.

    Four fixed header lines then the detail, which is last precisely because it
    is the only field that can be multi-line. A v1/v2 entry cannot be read here
    (it has no `lib_sorries` line), which is the intended outcome: its key
    differs anyway, and a body this cannot parse is treated as a miss rather
    than as a count of zero holes.
    """
    import cas
    hit = cas.lookup(key, VERDICT_EXT)
    if not hit:
        return None
    try:
        with open(hit, "rb") as f:
            body = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    lines = body.split("\n")
    if len(lines) < 4:
        return None
    try:
        n_sorries = int(lines[1] or 0)
        lib_sorries = int(lines[2])
    except ValueError:
        return None
    return (lines[0] == "ok", n_sorries, lib_sorries, lines[3],
            "\n".join(lines[4:]).strip("\n"))


def _publish_verdict(key, ok, n_sorries, lib_sorries, lib_detail, detail):
    import cas
    try:
        cas.publish(key, VERDICT_EXT,
                    (("ok" if ok else "fail") + "\n" + str(n_sorries) + "\n"
                     + str(lib_sorries) + "\n" + lib_detail + "\n"
                     + detail + "\n").encode())
    except OSError:
        pass          # a cache that cannot be written must not fail the check


def _lib_totals(lib: dict) -> tuple:
    """(n_sorries, detail) over the MEASURED library modules, or (-1, "") when
    none was. The detail is `stem:name,name; stem:name`, and it is carried
    because "3" does not say which three and a reader who is deciding whether
    to trust a proof needs to open one."""
    measured = [(stem, got) for stem, got in sorted(lib.items())]
    if not measured:
        return _LIB_UNMEASURED, ""
    total = sum(got[0] for _stem, got in measured)
    # Newline between modules, TAB between names, and nothing else. The earlier
    # `"; "` / `","` spelling was a separator a Lean identifier could contain
    # (`Foo.bar, baz` is a legal name), which makes the record's own encoding
    # ambiguous for exactly the modules whose census matters most — the dylib
    # proofs' per-export theorems. TAB and NEWLINE are not in an identifier.
    detail = "\n".join(stem + "\t" + "\t".join(got[1])
                       for stem, got in measured)
    return total, detail


def _lib_from_record(lib: dict, lib_sorries: int, lib_detail: str) -> dict:
    """The measured library as `library_census` would return it, from a record.

    A verdict read from the cache carries the library's census with it, so the
    cached path needs no second measurement. The distinction that matters is
    preserved exactly: `lib_sorries == _LIB_UNMEASURED` yields `{}` — absent,
    i.e. UNMEASURED — and never a set of modules with zero holes.
    """
    if lib_sorries == _LIB_UNMEASURED:
        return {}
    out = {}
    for entry in lib_detail.split("\n"):
        stem, _, names = entry.partition("\t")
        if stem:
            named = tuple(n for n in names.split("\t") if n)
            out[stem] = (len(named), named)
    return out


def _census_lines(proof_path, lib_dir, n_sorries, lib: dict) -> list:
    """The report, as lines. Empty when there is nothing to report.

    Silence is the clean case and is the point: a proof with no admitted holes,
    no vacuous declarations and a measured clean library produces NO output, so
    a line in the log is always a fact somebody has to look at. A proof with a
    hole and a proof with a vacuous theorem produce DIFFERENT lines, which is
    the whole of what this instrument is for — they used to be the same `PASS`
    with the same empty record beside it.

    `n_sorries` is `None` when the generated file's holes were not measured —
    the read-only path, which cannot know them without elaborating. It is NOT
    then reported as zero: the vacuous count and the library's census are both
    still reported, because neither needs elaboration, and the omission of the
    one figure is visible as the absence of the clause naming it.
    """
    try:
        with open(proof_path, "r", errors="replace") as f:
            vacuous = vacuous_declarations(f.read())
    except OSError:
        vacuous = []
    lib_vacuous = []
    for stem in LIBRARY_MODULES:
        path = os.path.join(lib_dir, stem + ".lean")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", errors="replace") as f:
                for name, shape, line in vacuous_declarations(f.read()):
                    lib_vacuous.append((f"{stem}.lean", name, shape, line))
        except OSError:
            continue
    lines = []
    if n_sorries or vacuous or n_sorries is None:
        holes = (f"{n_sorries} declaration(s) admitted a `sorry`, " if n_sorries
                 is not None else "hole census not measured, ")
        lines.append(
            f"proof census: {os.path.basename(proof_path)} — "
            + holes
            + f"{len(vacuous)} vacuous (admitted by a complete proof and "
              f"asserting nothing)")
        for name, shape, line in vacuous:
            lines.append(f"  vacuous, {shape}: {name} (line {line})")
    total, detail = _lib_totals(lib)
    if total == _LIB_UNMEASURED:
        # Unconditional, and this is the point of the whole library half of the
        # census. A proof with no local holes and an unmeasured library is a
        # proof resting on holes nobody has counted, and reporting nothing is
        # the one thing this instrument must never do: silence is the clean
        # case, and "clean" is a claim.
        lines.append("  library: hole census NOT MEASURED (no lean, or no "
                     "recorded measurement of the library) — this is NOT a "
                     "report of zero, and a proof with no local `sorry` is "
                     "still resting on whatever the library admits")
    elif total:
        # One line per module. A single line carrying all four would be a
        # 200-character wrap in a terminal and a mismatch of prefix in a log,
        # and the per-module split is the readable form anyway: "Refine
        # dylib_export_contract_stub" is the whole finding.
        lines.append(f"  library: {total} declaration(s) in {len(lib)} "
                     f"module(s) admitted a `sorry`:")
        for entry in detail.split("\n"):
            stem, _, names = entry.partition("\t")
            named = [n for n in names.split("\t") if n]
            lines.append(f"    {stem}: " + (", ".join(named) if named
                                            else "none (measured, clean)"))
    for where, name, shape, line in lib_vacuous:
        lines.append(f"  library vacuous, {shape}: {name} ({where}:{line})")
    return lines


def census_report(proof_path: str, repo_root: str | None = None) -> list:
    """The census of `proof_path` and of the library it rests on, as lines.

    No Lean run: the generated file's holes need elaboration, so they are NOT
    read here and the line that reports them is omitted rather than guessed —
    `check_proof_cached` is what supplies them, and a caller that wants the
    whole picture should call `proof_census` and use its `lines`. What this
    DOES need no elaboration, and is what a read-side display wants, is the two
    halves that were invisible before: the vacuous declarations in the
    generated file and in `lib/`, and the library's hole census as last
    measured.

    The split is deliberate. There is exactly one place in this module that can
    see everything (`proof_census`, which is also where the verdict is decided)
    and this is a second, cheaper, deliberately partial one — a read-side
    display that had to run Lean to print a figure would be a read-side display
    nobody runs.
    """
    root = repo_root or _default_root()
    lib_dir = os.path.join(root, "lib")
    lean = find_lean(root)
    lib = {}
    if lean:
        try:
            lib = library_census(lean, lib_dir, measure=False)
        except Exception:
            lib = {}
    if not os.path.isfile(proof_path):
        return [f"proof census: {proof_path} does not exist"]
    # `None`, not 0: the generated file's holes need elaboration and this path
    # does not elaborate. Reporting 0 here would be the exact conflation the
    # library half of this instrument exists to prevent, one level up.
    return _census_lines(proof_path, lib_dir, None, lib)


def _emit_census(lines: list) -> None:
    """Write the census to stderr, where a diagnostic belongs.

    stderr rather than stdout on purpose: `fire.py` owns stdout and prints
    `Proof: <path>` there, and this has to appear without a one-line change in
    a file four other agents are working in. It is also the channel every test
    harness in this repository already captures, so the figure reaches a human
    reading a failure without anyone wiring anything up.

    `FORMAL_CENSUS=off` silences it, and `always` prints it even when clean —
    for a run whose purpose is to state the figure rather than to be alarmed by
    it. The default is "print when there is something to say", which is what
    keeps the common case quiet and a line meaningful.
    """
    mode = (os.environ.get("FORMAL_CENSUS") or "").strip().lower()
    if mode == "off":
        return
    if not lines and mode != "always":
        return
    for line in lines or ["proof census: no admitted `sorry`, no vacuous "
                          "declaration, library measured clean"]:
        print(f"  [{line}]", file=sys.stderr)


def check_proof_cached(proof_path: str, repo_root: str | None = None,
                       timeout: float | None = None) -> tuple:
    """check_proof, memoised on the exact inputs. Third element is True on a
    cache hit (nothing was run); fourth is the number of declarations that
    admitted a `sorry` (see `_run_lean`). Both verdicts are cached: a
    known-failing example is just as deterministic as a passing one, and
    re-deriving it with a multi-minute Lean run is what made iterating on the
    suite painful.

    The ONE thing not cached is a bound breach, and that is a distinction of
    kind rather than of convenience: the CAS key is a pure function of the
    proof's bytes and the toolchain, while "exceeded 600s wall" is a fact about
    this machine at this moment. `proof_census` returns it uncached, `ok=False`,
    and with the hole census `None` rather than 0.

    Those four elements are the whole contract and they are unchanged. What is
    new is that the CENSUS IS NOW READ: `proof_census` records the library's
    holes and the vacuous declarations alongside the generated file's, and this
    writes them to stderr on every call. `n_sorries` used to be returned to
    exactly one caller, stored in a dict by `formal/build.py` and read by nobody
    — a proof with a thousand `sorry`s and a proof with none printed the same
    `PASS`, and the instrument that was supposed to prevent that was itself
    unread. See `Census` and `_emit_census`.
    """
    c = proof_census(proof_path, repo_root, timeout)
    _emit_census(c.lines)
    return c.ok, c.detail, c.cached, c.n_sorries


def check_proof(proof_path: str, repo_root: str | None = None,
                timeout: float | None = None) -> tuple[bool, str]:
    ok, detail, _, _ = check_proof_cached(proof_path, repo_root, timeout)
    return ok, detail


def _run_lean(proof_path: str, lib_dir: str, lean: str, wall_s: float,
              cpu_s: float | None = None) -> tuple:
    """`(ok, detail, n_sorries, exceeded)`.

    The fourth element is the bound this run broke, or `None`. It is a separate
    return rather than a shape of `detail` because the two callers need it for
    different things: `proof_census` refuses to CACHE a breach (a machine's
    property, not the proof's), and every reader of `detail` needs it printed.
    Folding it into `detail` would make "was this a failure or a bound" a string
    match, which is the thing this module keeps arguing against.

    `n_sorries` is the number of declarations Lean reports as "uses `sorry`" —
    the ONLY sound way to count holes, and the reason this census is worth
    carrying.  Grepping the generated source for the word counts a
    `all_goals first | … | sorry` fallback that was never reached (a tactic
    alternative that loses is still text), so a textual count is a count of
    *hypothetical* holes and never goes down.  Worse, the doc this replaces
    counted the greps of a plain `lean` run, which reports nothing at all when
    Lean serves a cached verdict — hence a figure that was neither the
    baseline nor the current state.  Lean emits the warning during
    elaboration, once per declaration that actually admitted a hole.

    ON **STDOUT**, not stderr, and that is measured rather than assumed: this
    function is handed `stdout + stderr` for exactly that reason, and a probe
    that reads only `result.stderr` sees an empty string for a run that really
    did report two holes in `lib/ProofLib.lean` — a hole census of zero,
    confidently, from a tool that was working perfectly. Anything here that
    parses `lean` output must read both streams.

    It says nothing at all about a `sorry` in an IMPORTED module, which is the
    other half of the census and lives in `library_census`; the two are counted
    apart on purpose, because "the file Lean read" and "the proof the file
    rests on" are different things and a single total would hide which one a
    hole is in.

    **A breach reports no count at all**, not zero: the elaborator was killed
    part-way through the file, so its warnings are a prefix of the answer. Zero
    is the one number that reads as "measured, clean", which is the failure this
    whole module is about — so `None` it is, which the report already knows how
    to render ("hole census not measured").
    """
    env = os.environ.copy()
    # ABSOLUTE, for the reason `library_census` states at its own `LEAN_PATH`
    # and which this site did not act on: the path is resolved against the
    # elaborating process's cwd, and the cwd below is the PROOF'S OWN DIRECTORY.
    # A caller that hands `proof_census` a relative `repo_root` — which is what
    # `repo_root="."` is, and what a bug doc's own reproduce command writes —
    # therefore resolved `lib` to `<proofdir>/lib`, and every import of
    # ProofLib failed with
    #
    #     error: unknown module prefix 'ProofLib'
    #     No directory 'ProofLib' or file 'ProofLib.olean' in the search path
    #     entries: <proofdir>  ./lib  <toolchain>
    #
    # **which is a verdict about the PROOF and not about the program.** It is
    # reported at `1:0`, before the theorem that was to be checked is read at
    # all, so every measurement taken that way is a measurement of a broken
    # search path — and it is CACHED, because `proof_verdict_key` hashes the
    # proof's bytes and the library's `.olean`s and neither of them records how
    # the run found the library, so one caller's relative root replays the same
    # false failure for every later caller with the same file.
    env["LEAN_PATH"] = os.pathsep.join(
        (os.path.dirname(os.path.abspath(proof_path)), os.path.abspath(lib_dir)))
    result = run_lean(lean, [os.path.basename(proof_path)], env=env,
                      wall_s=wall_s, cpu_s=cpu_s,
                      cwd=os.path.dirname(os.path.abspath(proof_path)))
    if result.exceeded:
        return False, result.exceeded, None, result.exceeded
    n_sorries = _census_from_output(
        (result.stdout or "") + (result.stderr or ""),
        _read_lines(proof_path))[0]
    if result.returncode != 0:
        return (False, (result.stderr or result.stdout or "lean failed").strip(),
                n_sorries, None)
    return True, "", n_sorries, None
