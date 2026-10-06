#!/usr/bin/env python3
"""Peak-memory budget for the self-hosted compiler (`./mojoc`), as a number.

The project's standard is that nothing we run needs more than 3-4 GB
(bugs/PERF_memory_over_4gb_is_a_bug.md). The self-hosted binary has no garbage
collector, so a pass that re-derives a working set per function, per module or
per call turns into gigabytes without changing a single output byte; such a
regression is invisible to every correctness check and only shows as RSS. This
test fails on the number.

Two cases, both measured with the binary's own RUSAGE_CHILDREN peak:

  snippet  `mojoc abfulltest_driver.mojo --dump-full` run from the repo root,
           which is what ab-native does per case. Compiling from the compiler's
           own source directory makes the binary run the self-host pre-pass
           over all ~60 compiler sources, so this is the FIXED cost of one
           invocation. Measured 17.6 GB before the 2026-09-30 leak hunt,
           0.44 GB after. Budget 1.5 GB.
  fire     `mojoc fire.py --dump-full` (the compiler compiling itself, the
           worst case). Measured 37 GB / SIGSEGV before, 12.2 GB after (it
           still ends with "AttributeError: platform" and writes no .ci:
           bugs/CODEGEN_selfhost_dumpfull_ends_in_attributeerror_platform.md).
           Budget 16 GB: a tripwire against the 23 GB-class regressions
           (a per-call dict copy) rather than a claim that 12 GB is acceptable;
           ratchet it down as the remaining sites in
           bugs/PERF_selfhost_memory_leak_hunt.md are closed.

`python3 test_selfhost_memory.py snippet|fire|all` (default: snippet). Needs a
built `./mojoc` (`make mojoc`). Run the `fire` case through tools/memslot.py.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
MOJOC = os.path.join(REPO, "mojoc")

GB = 1024 ** 3
CASES = {
    # name: (argv after mojoc, budget bytes, output .ci that must not be left behind)
    "snippet": (["abfulltest_driver.mojo", "--dump-full"], int(1.5 * GB), "abfulltest_driver.ci"),
    "fire": (["fire.py", "--dump-full"], 16 * GB, "fire.ci"),
}


def _peak_of(argv):
    """Peak RSS in bytes of `argv` run to completion, from a fresh helper
    interpreter so RUSAGE_CHILDREN is this command's own peak and not the
    maximum over every child this process ever spawned."""
    probe = (
        "import resource, subprocess, sys\n"
        "r = subprocess.run(sys.argv[1:], capture_output=True)\n"
        "sys.stderr.write(str(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss) + ' ' + str(r.returncode))\n"
    )
    env = dict(os.environ, MOJO_HOME=REPO)
    r = subprocess.run([sys.executable, "-c", probe] + argv, cwd=REPO, env=env,
                       capture_output=True, timeout=1800)
    maxrss, rc = r.stderr.decode().split()[-2:]
    maxrss = int(maxrss)
    if sys.platform != "darwin":
        maxrss *= 1024                       # Linux reports KiB, macOS bytes
    return maxrss, int(rc)


def run_case(name):
    args, budget, out = CASES[name]
    path = os.path.join(REPO, out)
    if os.path.exists(path):
        os.remove(path)
    peak, rc = _peak_of([MOJOC] + args)
    if os.path.exists(path):
        os.remove(path)
    ok = peak <= budget
    print(f"{'PASS' if ok else 'FAIL'}  {name}: peak {peak / GB:.2f} GB "
          f"(budget {budget / GB:.1f} GB, exit {rc})")
    return ok


def main():
    if not os.path.exists(MOJOC):
        print(f"{MOJOC} not built - run `make mojoc` first")
        return 1
    which = sys.argv[1] if len(sys.argv) > 1 else "snippet"
    names = list(CASES) if which == "all" else [which]
    results = [run_case(n) for n in names]
    print(f"Results: {sum(results)} passed, {len(results) - sum(results)} failed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
