#!/usr/bin/env python3
"""Toolchain-plumbing proof: a mixed C ( -fgimple ) / C++20 build+link+run,
routed through this project's REAL compile/link code — not a bypassed
scratch script.

This is Milestone A of compiled-path generator support (see
BACKLOG-CODEGEN.md / the generator-support milestone history): a later
milestone (B) will make gimple_codegen.py emit real C++20
`co_yield`/`std::coroutine_handle` code for generator function bodies,
compiled by g++ into its own object and linked into an otherwise all-C
-fgimple program through a thin `extern "C"` API. This test does not touch
generator detection or codegen at all (deliberately: zero changes to
gimple_codegen.py this milestone) — it only proves the underlying toolchain
plumbing a later milestone will need:

  1. build_config.find_gxx() locates a real g++ (MacPorts g++-mp-15 here),
     mirroring find_gcc()'s fallback chain.
  2. fire_runtime.h compiles clean under g++ -std=c++20 (verified separately,
     see runtime/fire_runtime.h; no changes were needed).
  3. fire.py's link_executable(..., cxx=True) — the REAL link-command
     builder factored out of build_executable() — picks g++ as the final
     link driver when told to, while build_stdlib_dylib.py's _dylink(...,
     link_driver=...) offers the same override for dylib links. This test
     exercises fire.py's link_executable directly (the exe-producing path,
     matching "compile, link, run, assert output" below) and additionally
     sanity-checks _dylink's link_driver plumbing builds a valid command
     list without actually needing a runnable dylib for this proof.

Concretely: a trivial extern "C" C++ function (poc_add) is compiled with
g++; a trivial C file that calls it is compiled with `gcc -fgimple`
(matching this project's normal C compile flags); the two objects are
linked into one executable via fire.py's real link_executable(cxx=True);
the executable is run and its output is checked.
"""
import os
import sys
import subprocess
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_config import find_gcc, find_gxx
import fire
import build_stdlib_dylib as bsd

GCC = find_gcc()
GXX = find_gxx()

_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


POC_CPP = """\
extern "C" long poc_add(long a, long b) { return a + b; }
"""

MAIN_C = """\
#include <stdio.h>
extern long poc_add(long a, long b);
int main(void) {
    long r = poc_add(3, 4);
    printf("%ld\\n", r);
    return (int)(r == 7 ? 0 : 1);
}
"""


def test_find_gxx():
    check("find_gxx() returns a usable g++ binary",
          shutil.which(GXX) is not None or os.path.exists(GXX), detail=GXX)
    out = subprocess.run([GXX, '--version'], capture_output=True, text=True)
    check("g++ --version succeeds", out.returncode == 0, detail=out.stderr)


def test_mixed_compile_link_run(wd):
    cpp_file = os.path.join(wd, 'poc.cpp')
    c_file = os.path.join(wd, 'main.c')
    with open(cpp_file, 'w') as f:
        f.write(POC_CPP)
    with open(c_file, 'w') as f:
        f.write(MAIN_C)

    cpp_o = os.path.join(wd, 'poc.o')
    c_o = os.path.join(wd, 'main.o')

    # Compile the C++ translation unit with g++ (real C++20 coroutine bodies
    # will eventually live here — this is a trivial extern "C" stand-in for
    # plumbing purposes only).
    r = subprocess.run([GXX, '-std=c++20', '-c', '-o', cpp_o, cpp_file],
                        capture_output=True, text=True)
    check("g++ compiles poc.cpp -> poc.o", r.returncode == 0, detail=r.stderr)

    # Compile the C translation unit with gcc -fgimple, matching this
    # project's normal C compile flags (see fire.py's build_executable /
    # build_stdlib_dylib.py's _OBJ_FLAGS).
    r = subprocess.run([GCC, '-fgimple', '-c', '-o', c_o, c_file],
                        capture_output=True, text=True)
    check("gcc -fgimple compiles main.c -> main.o", r.returncode == 0, detail=r.stderr)

    if not (os.path.exists(cpp_o) and os.path.exists(c_o)):
        return

    # Link through the REAL project code: fire.py's link_executable(), the
    # exact function build_executable() itself calls for its final link
    # step, with cxx=True selecting g++ (find_gxx()) as the link driver —
    # required to correctly pull in the C++ runtime bits (libstdc++) a real
    # C++20 coroutine object would need.
    exe_file = os.path.join(wd, 'mixed_exe')
    result = mojo.link_executable([c_o, cpp_o], exe_file, cxx=True)
    check("link_executable(cxx=True) links main.o + poc.o via g++",
          result.returncode == 0, detail=result.stderr)

    if not os.path.exists(exe_file):
        return
    os.chmod(exe_file, 0o755)

    run = subprocess.run([exe_file], capture_output=True, text=True, timeout=10)
    check("mixed executable runs and returns success (poc_add(3,4)==7)",
          run.returncode == 0, detail=f"returncode={run.returncode} stderr={run.stderr}")
    check("mixed executable prints 7", run.stdout.strip() == "7",
          detail=f"stdout={run.stdout!r}")


def test_link_executable_default_still_gcc():
    """cxx=False (the default) must still pick gcc — build_executable's
    existing all-C link behavior must be completely unaffected by this
    milestone's plumbing addition."""
    check("mojo._GCC_BIN / mojo._GXX_BIN are both resolved to strings",
          isinstance(mojo._GCC_BIN, str) and isinstance(mojo._GXX_BIN, str))
    # Directly probe link_executable's driver selection without actually
    # linking anything (empty obj list -> gcc/g++ just report a "no input
    # files" style error, which is fine; we only care which binary ran).
    import unittest.mock as mock
    with mock.patch('mojo.subprocess.run') as m:
        mojo.link_executable(['a.o'], 'out', cxx=False)
        cmd = m.call_args[0][0]
        check("link_executable(cxx=False) uses gcc as driver", cmd[0] == mojo._GCC_BIN,
              detail=str(cmd))
    with mock.patch('mojo.subprocess.run') as m:
        mojo.link_executable(['a.o'], 'out', cxx=True)
        cmd = m.call_args[0][0]
        check("link_executable(cxx=True) uses g++ as driver", cmd[0] == mojo._GXX_BIN,
              detail=str(cmd))


def test_dylink_driver_override():
    """build_stdlib_dylib.py's _dylink(..., link_driver=...) — the dylib-link
    equivalent of fire.py's link_executable(cxx=True) — builds a command
    list using the override driver, and defaults to `gcc` unchanged when no
    override is given (ordinary stdlib dylib builds are unaffected)."""
    cmd_default = bsd._dylink(GCC, '/tmp/out.dylib', ['a.o', 'b.o'])
    check("_dylink() with no override still uses gcc", cmd_default[0] == GCC,
          detail=str(cmd_default))
    cmd_override = bsd._dylink(GCC, '/tmp/out.dylib', ['a.o', 'b.o'], link_driver=GXX)
    check("_dylink(link_driver=g++) uses g++ as the link driver",
          cmd_override[0] == GXX, detail=str(cmd_override))
    check("_dylink(link_driver=...) still includes all objects",
          'a.o' in cmd_override and 'b.o' in cmd_override, detail=str(cmd_override))


def main():
    wd = tempfile.mkdtemp(prefix='mojo_mixed_cpp_link_')
    try:
        test_find_gxx()
        test_mixed_compile_link_run(wd)
        test_link_executable_default_still_gcc()
        test_dylink_driver_override()
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
