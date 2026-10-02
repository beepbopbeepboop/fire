#!/usr/bin/env python3
"""x86-64 PARITY: constructs arm64 lowers that x86-64 refused, checked on BOTH.

Every case here is one the two architectures used to answer differently about:
arm64 built it and ran it, x86-64 refused the source, or the reverse.  That
divergence is the defect this file exists to keep closed, and it is why each
case is checked on both backends rather than on the host's: a one-sided
assertion stays green through the whole class, because the backend under test
is the one that changed.

Three properties per case, and the third is the one that makes the other two
worth anything:

  1. arm64 builds it and its output matches CPython's;
  2. x86-64 builds it and its output matches CPython's;
  3. the expected output is whatever CPython prints for the same computation,
     run here, at test time — not a constant written by the person who wrote
     the lowering.  A constant is an assertion about a lowering made against
     itself, and a program that computes the right number for the wrong reason
     passes it.

`REFUSALS` are the other direction: a construct neither machine may lower, and
both must say so with the SAME words.  A construct that is genuinely absent
from the value model is better refused than emitted, and "one architecture
crashes and the other declines" is the shape that must not survive.

The first construct here is the read-modify-write through a subscript
(`q[0] += 5`), which arm64 had as `_emit_subscript_aug` and x86-64 refused
outright — bugs/FORMAL_x86_64_augmented_assignment_through_a_subscript_is_refused.md.
The refusal beside it is the same construct over a list of strings, where both
backends used to reach the integer ALU with two `char *` operands.

    python3 test_formal_x86_64_parity.py [-v] [--list]
"""

import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 120
BACKENDS = ("arm64", "x86_64")


# (name, mojo source, cpython source).  The two are the same program; the
# CPython one exists so the expectation is computed rather than asserted.
#
# `Pointer` is spelled and annotated because the pointee WIDTH is what the
# read-modify-write has to agree with: `q[0] += 5` on `Pointer[Int32]` is
# 8-byte-granular arithmetic on a 4-byte element, and a lowering that forgets
# the width writes three bytes of a neighbour.
CASES = [
    ("aug_through_int32_pointer",
     "def main():\n"
     "    var q: Pointer[Int32] = malloc(16)\n"
     "    q[0] = 10\n"
     "    q[0] += 5\n"
     "    q[1] = 3\n"
     "    q[1] *= 7\n"
     "    printf(\"a=%d b=%d\", q[0], q[1])\n"
     "    return 0\n",
     "import ctypes\nimport sys\n"
     "# `create_string_buffer`, not `CDLL('libc').malloc`: ctypes's\n"
     "# default restype is `c_int`, which TRUNCATES a 64-bit malloc\n"
     "# result, so the oracle itself segfaults before it computes\n"
     "# anything — a reference that cannot run asserts nothing.\n"
     "_buf = ctypes.create_string_buffer(64)\n"
     "def main():\n"
     "    q = ctypes.cast(_buf, ctypes.POINTER(ctypes.c_int32))\n"
     "    q[0] = 10\n"
     "    q[0] += 5\n"
     "    q[1] = 3\n"
     "    q[1] *= 7\n"
     "    sys.stdout.write(\"a=%d b=%d\" % (q[0], q[1]))\n"
     "    return 0\n"),
    # Every operator the shared table supports, on one buffer, so a table that
    # loses a row shows up as a refusal naming it rather than as a program that
    # quietly stops being lowered.  `-` is the one with a left operand that is
    # NOT the accumulator: for `p[0] -= 3` the old element is the LEFT operand
    # and 3 the right, and reversing them is a different answer.
    ("aug_every_operator",
     "def main():\n"
     "    var p: Pointer[Int] = malloc(64)\n"
     "    p[0] = 100\n"
     "    p[0] -= 30\n"
     "    p[1] = 6\n"
     "    p[1] *= 7\n"
     "    p[2] = 0xF0\n"
     "    p[2] &= 0x3C\n"
     "    p[3] = 0xF0\n"
     "    p[3] |= 0x0F\n"
     "    p[4] = 0xFF\n"
     "    p[4] ^= 0x0F\n"
     "    p[5] = 1\n"
     "    p[5] <<= 4\n"
     "    p[6] = 256\n"
     "    p[6] >>= 3\n"
     "    printf(\"%d %d %d\", p[0], p[1], p[2])\n"
     "    printf(\" %d %d %d\", p[3], p[4], p[5])\n"
     "    printf(\" %d\", p[6])\n"
     "    return 0\n",
     "import ctypes\nimport sys\n"
     "# `create_string_buffer`, not `CDLL('libc').malloc`: ctypes's\n"
     "# default restype is `c_int`, which TRUNCATES a 64-bit malloc\n"
     "# result, so the oracle itself segfaults before it computes\n"
     "# anything — a reference that cannot run asserts nothing.\n"
     "_buf = ctypes.create_string_buffer(64)\n"
     "def main():\n"
     "    p = ctypes.cast(_buf, ctypes.POINTER(ctypes.c_int64))\n"
     "    p[0] = 100; p[0] -= 30\n"
     "    p[1] = 6;   p[1] *= 7\n"
     "    p[2] = 0xF0; p[2] &= 0x3C\n"
     "    p[3] = 0xF0; p[3] |= 0x0F\n"
     "    p[4] = 0xFF; p[4] ^= 0x0F\n"
     "    p[5] = 1;   p[5] <<= 4\n"
     "    p[6] = 256; p[6] >>= 3\n"
     "    sys.stdout.write(\"%d %d %d %d %d %d %d\" % tuple(p[i] for i in range(7)))\n"
     "    return 0\n"),
    # The same seven values JOINED, read back through the pointer rather than
    # through the names above, because the case that found the real bug in the
    # first lowering of this construct read the element back and saw an
    # ADDRESS: `mov [rax], rax` stores the element's own pointer into the
    # element, which is invisible to a case that only checks the arithmetic
    # happened and shows up the moment anything reads the buffer afterwards.
    # The values are printed from a SECOND buffer walk, so the store's target
    # and the store's value are separately observable.
    # A ONE-BYTE element. `UInt8` is the case where the load and the store have
    # to agree on the width: a 64-bit store into a one-byte element overwrites
    # the seven bytes after it, which on a `malloc`'d buffer is a silent
    # corruption and not a fault, so the value of the NEXT element is the
    # evidence.
    ("aug_through_byte_pointer",
     "def main():\n"
     "    var p: Pointer[UInt8] = malloc(8)\n"
     "    p[0] = 200\n"
     "    p[0] += 55\n"
     "    p[1] = 9\n"
     "    printf(\"a=%d b=%d\", p[0], p[1])\n"
     "    return 0\n",
     "import ctypes\nimport sys\n"
     "# `create_string_buffer`, not `CDLL('libc').malloc`: ctypes's\n"
     "# default restype is `c_int`, which TRUNCATES a 64-bit malloc\n"
     "# result, so the oracle itself segfaults before it computes\n"
     "# anything — a reference that cannot run asserts nothing.\n"
     "_buf = ctypes.create_string_buffer(64)\n"
     "def main():\n"
     "    p = ctypes.cast(_buf, ctypes.POINTER(ctypes.c_uint8))\n"
     "    p[0] = 200; p[0] += 55\n"
     "    p[1] = 9\n"
     "    sys.stdout.write(\"a=%d b=%d\" % (p[0], p[1]))\n"
     "    return 0\n"),
    # A LIST element, so the address computation under test is the bounds-
    # checked blob walk rather than `base + i*width`, and so a negative index
    # (which wraps like Python before the bound is checked) is exercised
    # through the read-modify-write rather than only through a read.
    ("aug_through_list_element",
     "import sys\n\n"
     "def main():\n"
     "    var a = [10, 20, 30]\n"
     "    a[1] += 5\n"
     "    a[-1] *= 2\n"
     "    printf(\"%d %d %d\", a[0], a[1], a[2])\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    a = [10, 20, 30]\n"
     "    a[1] += 5\n"
     "    a[-1] *= 2\n"
     "    sys.stdout.write(\"%d %d %d\" % (a[0], a[1], a[2]))\n"
     "    return 0\n"),
    # The index is a CALL, so the address has to be computed ONCE. Re-evaluating
    # it for the write would read and write two different elements of a list the
    # call in between could have changed, which is the whole reason this shape is
    # a separate emitter rather than the plain-name one with a different store.
    ("aug_index_is_a_call",
     "import sys\n\ndef bump():\n"
     "    return 1\n"
     "\n"
     "def main():\n"
     "    var a = [10, 20, 30]\n"
     "    a[bump()] += 100\n"
     "    printf(\"%d %d %d\", a[0], a[1], a[2])\n"
     "    return 0\n",
     "import sys\n\ndef bump():\n"
     "    return 1\n"
     "\n"
     "def main():\n"
     "    a = [10, 20, 30]\n"
     "    a[bump()] += 100\n"
     "    sys.stdout.write(\"%d %d %d\" % (a[0], a[1], a[2]))\n"
     "    return 0\n"),
]


# A construct NEITHER machine may lower, and both must refuse it with the same
# words: a `+=` whose element and whose value are both `char *` is integer
# arithmetic on two addresses.  arm64's subscript-augmented path reached the
# ALU without asking, so `a[0] += "x"` over a list of strings BUILT there and
# printed the length of a pointer sum; x86-64 refused.  One architecture
# answering and the other declining is the shape this file exists to end, and
# the check is `refuse:`-shaped for the same reason `test_formal_run.py`'s are:
# nothing about the program's OUTPUT can carry the assertion, because the
# assertion is that it must not have one.
REFUSALS = [
    ("aug_on_two_strings_refused_identically",
     "def main():\n"
     "    var a = [\"ab\", \"cd\"]\n"
     "    a[0] += \"x\"\n"
     "    printf(\"%d\\n\", len(a[0]))\n"
     "    return 0\n",
     "'+=' on two strings is refused"),
]

# The other direction, and it is a PER-PLATFORM limit rather than a shared one:
# a NINE-argument call.  arm64 grew AAPCS's stack-argument convention on
# 2026-10-01, so argument 8 travels in the caller's frame and both ends of it
# load and store there; x86-64's SysV convention — six integer argument
# registers and then the stack — is still unimplemented here, so the ninth
# argument is still refused there.  Both answers are correct for their
# platform, and the point of pinning the x86-64 one is that it is a STATED
# LIMIT rather than an oversight: if a later change implements the SysV stack
# area, this case starts failing and says so
# (`bugs/FORMAL_struct_pack_over_eight_arguments.md` §"the x86-64 gap", which
# is the same wall from the `struct.pack` side).
#
# `test_formal_run.py`'s `nine_arguments_arrive` is the arm64 half, and the
# nine-parameter CALLEE with no call site is pinned there too — a dylib export
# is the only way to reach a function without a call site, and
# `_load_home_from_stack` is what such a function's prologue uses.
X86_ONLY_REFUSALS = [
    ("nine_arguments_are_still_refused_on_x86_64",
     "def nine(a0: int, a1: int, a2: int, a3: int, a4: int,\n"
     "         a5: int, a6: int, a7: int, a8: int) -> int:\n"
     "    return a8 * 10000 + a0\n\n"
     "def main() -> int:\n"
     "    printf(\"nine=%d\", nine(1, 2, 3, 4, 5, 6, 7, 8, 9))\n"
     "    return 0\n",
     "9 arguments exceeds the"),
]


def build(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run(path, backend, timeout=RUN_TIMEOUT):
    """Execute a built image, under Rosetta 2 when it is an x86-64 one.

    The x86-64 backend's whole subject is an image that RUNS, so a case that
    quietly stopped running — because the host cannot execute it — would pass
    every assertion that only compared build output.  `arch -x86_64` is what
    makes that a failure rather than a skip.

    Selected by the BACKEND rather than applied to whatever was built: on an
    arm64 host `arch -x86_64 <an arm64 image>` is "Bad CPU type in executable",
    which is a failure that reads as the host's fault and is really the harness
    asking the wrong machine to run the program.
    """
    argv = [path]
    if (backend == "x86_64" and platform.machine() in ("arm64", "aarch64")
            and sys.platform == "darwin"):
        argv = ["arch", "-x86_64", path]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def cpython_answer(source, tmpdir, name):
    """CPython's stdout and exit status for `source` + `main()`, run now."""
    py = os.path.join(tmpdir, name + ".ref.py")
    with open(py, "w") as f:
        f.write(source + "\nmain()\n")
    ref = subprocess.run([sys.executable, py], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    return ref.returncode, ref.stdout


def run_case(name, mojo_src, cpython_src, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(mojo_src)
    want_exit, want_out = cpython_answer(cpython_src, tmpdir, name)
    if want_exit != 0:
        return False, (f"the CPython reference itself failed (exit "
                       f"{want_exit}); a case whose oracle does not run asserts "
                       f"nothing")
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(src, out, backend)
        if rc != 0:
            return False, f"--backend={backend} did not build: {text.strip()[-300:]}"
        if not os.path.isfile(out):
            return False, f"--backend={backend} reported success, wrote no binary"
        r = run(out, backend)
        if r.returncode != want_exit:
            return False, (f"--backend={backend} exited {r.returncode}, CPython "
                           f"exits {want_exit}; stderr: {r.stderr.strip()[:160]}")
        if r.stdout != want_out:
            return False, (f"--backend={backend} printed {r.stdout[:120]!r}, "
                           f"CPython prints {want_out[:120]!r}")
        if verbose:
            print(f"      {backend}: {r.stdout[:60]!r} exit={r.returncode}")
    return True, ""


def run_refusal(name, mojo_src, needle, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(mojo_src)
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(src, out, backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct that has no "
                           f"representation (expected a refusal naming "
                           f"{needle!r}) — the binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-300:]}")
    if verbose:
        print(f"      refused identically on arm64 and x86-64: {needle!r}")
    return True, ""


def run_x86_refusal(name, mojo_src, needle, tmpdir, verbose):
    """`run_refusal` for a limit that is ONE PLATFORM's, not the model's.

    `run_refusal` requires both backends to refuse with the same words, which
    is the right assertion for a construct absent from the value model and the
    WRONG one here: arm64 lowers a nine-argument call, because AAPCS's stack
    area is implemented on it. So this builds x86-64 only, requires the refusal,
    and — deliberately — does NOT require arm64 to refuse, because a later
    change implementing the SysV stack area would make arm64's behaviour
    irrelevant to this case rather than wrong.
    """
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(mojo_src)
    out = os.path.join(tmpdir, f"{name}.x86_64")
    rc, text = build(src, out, "x86_64")
    if rc == 0:
        return False, ("x86-64 BUILT a construct its own SysV convention does "
                       "not yet implement (six integer argument registers, and "
                       "the stack area past them is unimplemented here); the "
                       "binary is the real answer")
    if needle not in text:
        return False, (f"x86-64 refused, but not naming {needle!r}: "
                       f"{text.strip()[-200:]}")
    if verbose:
        print(f"      x86-64 refused, naming {needle!r}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--list", action="store_true", help="list the cases and exit")
    ap.add_argument("cases", nargs="*", help="run only these cases")
    args = ap.parse_args()

    if args.list:
        for name, _s, _c in CASES:
            print(f"  case    {name}")
        for name, _s, needle in REFUSALS:
            print(f"  refusal {name}  ({needle!r})")
        for name, _s, needle in X86_ONLY_REFUSALS:
            print(f"  x86-only refusal {name}  ({needle!r})")
        return 0

    known = ({c[0] for c in CASES} | {c[0] for c in REFUSALS}
             | {c[0] for c in X86_ONLY_REFUSALS})
    wanted = ([(c, False) for c in CASES] + [(c, True) for c in REFUSALS]
              + [(c, "x86") for c in X86_ONLY_REFUSALS])
    if args.cases:
        missing = set(args.cases) - known
        if missing:
            print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
            return 2
        wanted = [c for c in wanted if c[0][0] in args.cases]

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for (name, mojo_src, third), is_refusal in wanted:
            try:
                if is_refusal == "x86":
                    ok, detail = run_x86_refusal(name, mojo_src, third, tmpdir,
                                                 args.verbose)
                elif is_refusal:
                    ok, detail = run_refusal(name, mojo_src, third, tmpdir,
                                             args.verbose)
                else:
                    ok, detail = run_case(name, mojo_src, third, tmpdir,
                                          args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:                       # report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                print(f"  PASS  {name}")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")

    total = passed + failed
    print(f"\nx86-64 formal parity: PASS={passed} FAIL={failed} "
          f"({total} case{'s' if total != 1 else ''})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
