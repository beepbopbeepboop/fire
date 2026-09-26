#!/usr/bin/env python3
"""Does the x86-64 machine model in lib/X86.lean agree with the hardware?

A machine model that has only been typechecked is worth very little: it can be
wrong in ways Lean's kernel will never notice, because every definition in it
is trivially well-typed.  The only check that means anything is running it and
comparing against the machine it claims to model.

So this builds every `formal/examples/*.mojo` for x86-64, RUNS the resulting
binary under Rosetta, then runs the same bytes through `x86_exec_exit` in the
Lean interpreter and compares the value left in RAX.  Two numbers, and both
matter:

  WRONG   the model ran to completion and disagreed — a semantic bug in the
          model, in the codegen, or in the comparison.
  NO-RUN  the model refused to continue: an opcode `x86_step` does not decode,
          or a fuel/sentinel problem.  A distinct failure, and the one a
          "close enough" reading of the model hides, because a run that stops
          early still leaves *a* value in RAX.

The exit status is the low byte of RAX (the kernel truncates a wait status), so
that is the window the comparison is made in; the model is also run at three
further inputs, where a disagreement is reported even though there is no
hardware to compare against.

Run: python3 formal/x86_64_model_test.py [-v]
Exit: 0 iff every example agrees.
"""

import glob
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import formal.build as B                                    # noqa: E402
import formal.lean as L                                     # noqa: E402

INPUTS = (10, 0, 3, 5)
"""The build's own test_input first (so it lines up with the binary), then
three more to keep the same instruction stream honest on other paths."""

LEAN_ENV_EXTRA = (os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "lib"),)


def _lean_and_lib():
    root = L._default_root()
    lean = L.find_lean(root)
    if not lean:
        return None, None
    L.ensure_library(lean, os.path.join(root, "lib"))
    return lean, os.path.join(root, "lib")


def _build_cases():
    """[(name, code, (base, entry), real_exit)] for every example."""
    cases = []
    for path in sorted(glob.glob(os.path.join("formal", "examples", "*.mojo"))):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            r = B.compile_formal(path, prove=False, check=False, arch="x86_64")
        except Exception as e:                              # noqa: BLE001
            cases.append((name, None, None, "BUILD-FAIL: %s" % e))
            continue
        real = None
        try:
            real = subprocess.run(["arch", "-x86_64", r["path"]],
                                  capture_output=True, text=True,
                                  timeout=60).returncode
        except Exception as e:                              # noqa: BLE001
            real = "RUN-FAIL: %s" % type(e).__name__
        cases.append((name, r["code"],
                      (r["info"]["base_addr"], r["info"]["func_offset"]), real))
    return cases


def _lean_source(cases):
    out = ["import X86", ""]
    out.append("def render : Option UInt64 → String")
    out.append("  | some v => toString v | none => \"NORUN\"")
    for name, code, addr, _real in cases:
        if code is None:
            continue
        base, entry = addr
        items = ", ".join("0x%02x" % b for b in code)
        out.append("def code_%s (a : Nat) : UInt8 :=" % name)
        out.append("  if a < %d then 0 else ([%s].getD (a - %d) 0)"
                   % (base, items, base))
        for n in INPUTS:
            # exit pc 0: X86State.init leaves the stack zeroed, so the entry
            # function's own `ret` pops 0 and the runner stops there.
            out.append("def run_%s_%d : Option UInt64 :=" % (name, n))
            out.append("  (x86_exec_exit (X86State.init %d %d) code_%s 0).map"
                       " (fun s => s.rax)" % (n, entry, name))
    for name, code, _addr, _real in cases:
        if code is None:
            continue
        for n in INPUTS:
            out.append('#eval! "%s/%d " ++ render (run_%s_%d)' % (name, n, name, n))
    return "\n".join(out) + "\n"


def main(argv):
    verbose = "-v" in argv
    lean, lib = _lean_and_lib()
    if not lean:
        print("lean not found (see ./lean-toolchain)")
        return 1
    cases = _build_cases()
    workdir = os.path.join("/tmp", "x86_model_test")
    os.makedirs(workdir, exist_ok=True)
    src = os.path.join(workdir, "ModelCheck.lean")
    with open(src, "w") as f:
        f.write(_lean_source(cases))
    env = dict(os.environ, LEAN_PATH=os.pathsep.join((workdir, lib)))
    cp = subprocess.run([lean, os.path.basename(src)], cwd=workdir, env=env,
                        capture_output=True, text=True, timeout=7200)
    got = {}
    for line in (cp.stdout + cp.stderr).splitlines():
        line = line.strip().strip('"')
        for n in INPUTS:
            if "/%d " % n in line:
                name, v = line.split("/%d " % n)
                got.setdefault(name, {})[n] = v
                break

    agree = wrong = norun = build = 0
    for name, code, _addr, real in cases:
        if code is None:
            build += 1
            print("  %-14s %s" % (name, real))
            continue
        v = got.get(name, {}).get(INPUTS[0], "NORUN")
        if v == "NORUN":
            norun += 1
            print("  %-14s NO-RUN: the model stopped before returning" % name)
            continue
        if isinstance(real, str) or int(v) & 0xFF != real:
            wrong += 1
            print("  %-14s real=%s model=%s  (low byte %s)"
                  % (name, real, v, int(v) & 0xFF))
            continue
        agree += 1
        if verbose:
            print("  %-14s ok: %s" % (name, v))
        for n in INPUTS[1:]:
            w = got.get(name, {}).get(n, "NORUN")
            if w == "NORUN":
                norun += 1
                print("  %-14s NO-RUN at input %d" % (name, n))
    print("x86-64 model vs hardware: agree %d  WRONG %d  NO-RUN %d  "
          "build-fail %d  (of %d)" % (agree, wrong, norun, build, len(cases)))
    return 1 if (wrong or norun or build) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
