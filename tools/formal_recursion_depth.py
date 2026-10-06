#!/usr/bin/env python3
"""The recursion/stack table: where each backend stops, against CPython.

**The measurement, not a test.** `test_formal_run.py` pins the BEHAVIOUR (the
two directions of the guard: deep is a status, shallow still answers) and
`TestTheStackFloorGuardIsWhatGatesTheValueTheorem` pins the guard's cost to the
proof layer. Neither says where the boundary IS, so a change to a frame size, to
`STACK_FLOOR_BUDGET_BYTES`, or to which prologues are guarded moves the boundary
and nothing notices.

**Each shape is written TWICE, and that is the point.** `test_formal_run.py`'s
CPython-pair group already learned this the hard way: a source with `printf` and
`var` in it is not a Python program, so "run the same text through `python3`" is
not available for it and the oracle has to be a second spelling of the same
computation. So each shape below carries a `.mojo` and a `.py` that compute the
same thing, and `test_formal_recursion.py` re-derives the expectation FROM the
`.py` at test time rather than from a constant written by the same person who
wrote the lowering.

CPython is the oracle and it is an awkward one here, which is why both its
answers are printed:

  * with the DEFAULT limit (1000) it raises `RecursionError` — exit 1, a
    traceback on stderr — somewhere around depth 995-1000, and where exactly is
    a property of CPython's own frame accounting;
  * with `sys.setrecursionlimit` RAISED it runs to any depth this table asks
    for, because CPython's recursion is bounded by its interpreter stack and a
    raised limit is a promise about the C stack that the caller has checked.
    That is the answer a formal program is compared against, because a formal
    image has no interpreter stack to overflow (see
    `formal/hostmods/sys.mojo::getrecursionlimit`).

So a row where CPython answers and the image refuses is NOT a contradiction: it
is the difference between the two stack accountings, and the table says so in
words rather than leaving a reader to guess which of the two is broken.

Three frame shapes, because the depth at which the guard fires is
`STACK_FLOOR_BUDGET_BYTES / frame_bytes` and the frame is the only thing in that
quotient a source change can move:

  * `few` — one parameter, one branch, one call. The minimum frame.
  * `many` — 64 locals before the branch, so the register allocator spills and
    the frame grows by the spill bytes.
  * `struct` — a method on a three-field struct, so the frame also reserves the
    receiver's block (`model.struct_constructor_sites`).

Run it:

    python3 tools/formal_recursion_depth.py                 # the whole table
    python3 tools/formal_recursion_depth.py --bisect        # + exact boundaries
    python3 tools/formal_recursion_depth.py --json          # machine-readable
    python3 tools/formal_recursion_depth.py --shape struct --backend arm64

Every build here is a four-function program, so this is light; wrap it in
`tools/memslot.py` anyway, as the project's rule asks for anything that compiles:

    python3 tools/memslot.py --gb 8 --label rectable -- \
        python3 tools/formal_recursion_depth.py --bisect

WHY A TOOL AND NOT A ROW IN `test_formal_run.py`: the boundary is a property of
the MACHINE (`ulimit -s` on the host), so a test asserting an exact depth would
fail on a host with a different stack and pass by accident on this one. What a
test CAN assert — and what `test_formal_recursion.py` asserts — is the RELATION
the boundary obeys: it is inside the budget, it is a status and a message rather
than 139/138, and it MOVES with the frame size. The exact numbers live here.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRE = os.path.join(HERE, "fire.py")

#: The depths the task asks for, plus one comfortably inside both budgets. `500`
#: and `900` are CPython's (below its default limit of 1000); `5000` and
#: `100000` are past every limit on the machine.
DEPTHS = (30, 500, 900, 5000, 100000)

#: How deep the bisection goes before it stops believing the machine. A frame is
#: at least 16 KiB (x86-64's blob region) and the budget is 7.5 MiB, so 20 000
#: is past any boundary reachable on a host whose stack is under 320 MB.
_BISECT_HI = 20000


# ── the shapes, each in both spellings ────────────────────────────────────
#
# The `.py` is the oracle and the `.mojo` is the image, and they are kept
# adjacent in the source so a change to one is a visible omission in the other
# rather than a silent divergence two hundred lines away.

_FEW_MOJO = (
    "def deep(n):\n"
    "    if n <= 0:\n"
    "        return 0\n"
    "    return 1 + deep(n - 1)\n"
    "\n"
    "def main(k):\n"
    "    printf(\"d=%d\", deep(k))\n"
    "    return 0\n")

_FEW_PY = (
    "def deep(n):\n"
    "    if n <= 0:\n"
    "        return 0\n"
    "    return 1 + deep(n - 1)\n"
    "\n"
    "def main(k):\n"
    "    print(\"d=%d\" % deep(k), end=\"\")\n"
    "\n"
    "main(DEPTH)\n")


def _many_locals(n=64):
    decls = "".join("    var v%d = %d\n" % (i, i) for i in range(n))
    py_decls = "".join("    v%d = %d\n" % (i, i) for i in range(n))
    mojo = (
        "def deep(n):\n" + decls +
        "    if n <= 0:\n"
        "        return 0\n"
        "    return 1 + deep(n - 1) + v0\n"
        "\n"
        "def main(k):\n"
        "    printf(\"d=%d\", deep(k))\n"
        "    return 0\n")
    py = (
        "def deep(n):\n" + py_decls +
        "    if n <= 0:\n"
        "        return 0\n"
    "    return 1 + deep(n - 1) + v0\n"
    "\n"
    "def main(k):\n"
    "    print(\"d=%d\" % deep(k), end=\"\")\n"
    "\n"
    "main(DEPTH)\n")
    return (mojo, py)


def _struct_frame():
    # `self.down(n - 1)` and `s.down(k)`, the method-call spellings: the bare
    # `S.down(s, k)` is what this backend REFUSES (`formal/build.py`'s method
    # call rewriting wants the receiver as the receiver), and a shape the
    # compiler refuses measures nothing about recursion.
    mojo = (
        "struct S:\n"
        "    var a: Int\n"
        "    var b: Int\n"
        "    var c: Int\n"
        "\n"
        "    fn down(self, n: Int) -> Int:\n"
        "        if n <= 0:\n"
        "            return 0\n"
        "        return 1 + self.down(n - 1)\n"
        "\n"
        "def main(k):\n"
        "    var s = S()\n"
        "    printf(\"d=%d\", s.down(k))\n"
        "    return 0\n")
    py = (
        "class S:\n"
        "    def __init__(self):\n"
        "        self.a = 0\n"
        "        self.b = 0\n"
        "        self.c = 0\n"
        "\n"
        "    def down(self, n):\n"
        "        if n <= 0:\n"
        "            return 0\n"
        "        return 1 + self.down(n - 1)\n"
        "\n"
        "def main(k):\n"
        "    print(\"d=%d\" % S().down(k), end=\"\")\n"
        "\n"
        "main(DEPTH)\n")
    return (mojo, py)


SHAPES = (
    ("few", _FEW_MOJO, _FEW_PY),
    ("many",) + _many_locals(),
    ("struct",) + _struct_frame(),
)

SHAPE_BY_NAME = {name: (name, mojo, py) for name, mojo, py in SHAPES}


# ── CPython ───────────────────────────────────────────────────────────────


def cpython_probe(py_source, depth, raised):
    """`(exit code, stdout, last stderr line)` for the oracle at `depth`.

    `raised` applies `sys.setrecursionlimit(10**6)` first, which is the
    "with the limit raised" column. The stderr line kept is the LAST one
    because a traceback's last line is the exception's own name, and that is
    the part a reader compares against this path's message.
    """
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR") or None) as td:
        src = os.path.join(td, "p.py")
        with open(src, "w") as f:
            f.write("import sys\n")
            if raised:
                f.write("sys.setrecursionlimit(1000000)\n")
            f.write(py_source.replace("main(DEPTH)", "main(%d)" % depth))
        try:
            p = subprocess.run([sys.executable, src], capture_output=True,
                               text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return (None, "", "TIMEOUT")
        err = [ln for ln in (p.stderr or "").splitlines() if ln.strip()]
        return (p.returncode, p.stdout, err[-1] if err else "")


# ── the backends ──────────────────────────────────────────────────────────


def build_and_run(mojo_source, depth, backend, workdir):
    """`(exit code, stdout, stderr)` for the formal image at `depth`.

    `-n` bakes the depth into the image (`formal/build.py`'s `test_input`), which
    is this path's only way to hand a program a number: the startup stub
    materializes it into the entry's first argument.
    """
    src = os.path.join(workdir, "p.mojo")
    with open(src, "w") as f:
        f.write(mojo_source)
    out = os.path.join(workdir, "p.bin")
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           "--backend=%s" % backend, "-n", str(depth), "-o", out, src]
    b = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                       cwd=HERE)
    if b.returncode != 0:
        return ("BUILD-FAILED", (b.stderr or b.stdout or "").strip()[-160:], "")
    try:
        r = subprocess.run([out], capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return ("TIMEOUT", "", "")
    return (r.returncode, r.stdout, (r.stderr or "").strip())


def bisect_boundary(mojo_source, backend, workdir):
    """`(largest depth that answers, first depth that refuses, its status)`.

    A bisection rather than a scan because the boundary is between 1 and 20 000
    and the scan is 20 000 builds. Monotone in the depth by construction: a
    deeper call's frames are a superset of a shallower one's, so "answered at
    d" implies "answered at every d' < d".
    """
    lo, hi, first = 1, _BISECT_HI, None
    while hi - lo > 1:
        mid = (lo + hi) // 2
        rc, _out, _err = build_and_run(mojo_source, mid, backend, workdir)
        if rc == 0:
            lo = mid
        else:
            hi, first = mid, rc
    return (lo, hi, first)


# ── rows and the report ───────────────────────────────────────────────────


def measure(shapes, backends, depths, do_bisect, workdir):
    rows = []
    for shape, mojo, _py in shapes:
        for backend in backends:
            row = {"shape": shape, "backend": backend}
            if do_bisect:
                lo, hi, first = bisect_boundary(mojo, backend, workdir)
                row.update(last_ok=lo, first_refused=hi, refusal_status=first)
            for depth in depths:
                rc, out, err = build_and_run(mojo, depth, backend, workdir)
                row["n=%d" % depth] = {"exit": rc, "stdout": out.strip(),
                                       "stderr": err.strip()}
            rows.append(row)
    return rows


def cpython_rows(shapes, depths):
    out = []
    for shape, _mojo, py in shapes:
        for raised in (False, True):
            row = {"shape": shape,
                   "column": "setrecursionlimit raised" if raised
                             else "default limit (1000)"}
            for depth in depths:
                rc, so, se = cpython_probe(py, depth, raised)
                row["n=%d" % depth] = {"exit": rc, "stdout": so.strip(),
                                       "stderr": se.strip()}
            out.append(row)
    return out


def _cell(c):
    if c["exit"] == "BUILD-FAILED":
        return "BUILD-FAILED"
    tag = "exit %s" % c["exit"]
    if c["stdout"]:
        tag += " " + c["stdout"]
    if "RecursionError" in c["stderr"]:
        tag += " RecursionError"
    elif c["stderr"]:
        tag += " " + c["stderr"][:60]
    return tag


def _verdict(shapes, backends, depths, do_bisect, workdir):
    print()
    print("CPython, the oracle (the same computation, the other spelling)")
    header = "  ".join("n=%d" % d for d in depths)
    print("  %-7s %-28s %s" % ("shape", "column", header))
    for row in cpython_rows(shapes, depths):
        print("  %-7s %-28s %s" % (
            row["shape"], row["column"],
            "  ".join(_cell(row["n=%d" % d]) for d in depths)))

    print()
    print("The backends")
    for shape, mojo, _py in shapes:
        for backend in backends:
            print("  --- %s / %s" % (shape, backend))
            for depth in depths:
                rc, out, err = build_and_run(mojo, depth, backend, workdir)
                tag = "exit %s" % rc
                if out:
                    tag += " " + out
                if err:
                    tag += "  stderr: " + err[:80]
                print("      %-9s %s" % ("n=%d" % depth, tag))
    if do_bisect:
        print()
        print("The boundary: largest depth that answers / first that refuses")
        for shape, mojo, _py in shapes:
            for backend in backends:
                lo, hi, first = bisect_boundary(mojo, backend, workdir)
                print("  %-7s %-7s last ok %6d, first refused %6d (exit %s)"
                      % (shape, backend, lo, hi, first))
    print()
    print("Read: a depth where CPython answers and the image refuses is the "
          "difference")
    print("between CPython's interpreter stack and this path's fixed frame, "
          "not a defect")
    print("in either. What must hold is that the refusal is a STATUS and a "
          "MESSAGE")
    print("(never 139/138), and that the boundary moves with the frame size.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", action="append", default=None,
                    choices=("arm64", "x86_64"),
                    help="restrict to one backend (default: both)")
    ap.add_argument("--shape", default=None,
                    choices=tuple(SHAPE_BY_NAME),
                    help="restrict to one frame shape")
    ap.add_argument("--depth", action="append", type=int, default=None,
                    help="a depth to measure (default: %s)" % (DEPTHS,))
    ap.add_argument("--bisect", action="store_true",
                    help="also find each boundary exactly (slower)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable rows on stdout")
    args = ap.parse_args()
    backends = tuple(args.backend or ("arm64", "x86_64"))
    depths = tuple(args.depth or DEPTHS)
    shapes = (SHAPE_BY_NAME[args.shape],) if args.shape else SHAPES
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR") or None) as td:
        if args.json:
            print(json.dumps(
                {"backends": measure(shapes, backends, depths,
                                     args.bisect, td),
                 "cpython": cpython_rows(shapes, depths)},
                indent=1, default=str))
        else:
            _verdict(shapes, backends, depths, args.bisect, td)
    return 0


if __name__ == "__main__":
    sys.exit(main())
