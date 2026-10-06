#!/usr/bin/env python3
"""Generated-code quality for the formal backends: size first, then speed.

Two questions, two halves, and they are kept apart on purpose:

* **How big is the emitted code?** An instruction count per program, for
  `arm64` and `x86_64`. This is the metric the peephole pass
  (`formal/peephole.py`) moves, and it is deterministic, so a change to it is
  a fact about a build rather than a measurement of a machine. Counted with
  the backends' own decoders — `formal/x86_64_decode.py`, and the `arm64`
  decoder in `formal/peephole.py` — so "instruction count" means "instructions
  this backend emitted and its machine model can execute", not "bytes".

* **How fast is it?** For a small benchmark set, the SAME function built three
  ways: this compiler (both backends), the host C compiler at `-O0`, and
  CPython. Three implementations of one function, run the same number of
  times, best-of-N wall clock. This is a comparison, not a claim of
  equivalence: the point is the SHAPE of the gap, which is what says whether
  the emitted code is doing anything the source did not ask for.

`--opt` builds every program through the peephole pass, so the same tool
reports the before/after of a change to it in one invocation:

    python3 tools/formal_bench.py                 # the census
    python3 tools/formal_bench.py --bench         # the three-way benchmark
    python3 tools/formal_bench.py --opt           # the census, peephole on
    python3 tools/formal_bench.py --opt --bench --json .tmp/b.json
"""
import argparse
import glob
import json
import os
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

ARCHES = ("arm64", "x86_64")


# ── the benchmark set ───────────────────────────────────────────────────────
#
# Three spellings of ONE function each, because a comparison needs three
# implementations of the same thing and not three different programs. The
# `.mojo` column is what the formal backends build; the `.c` column is what
# `gcc -O0` builds; the `.py` column is what CPython runs. All three return
# the same number, which the harness CHECKS rather than assumes — a
# benchmark comparing three implementations that compute three different
# answers measures nothing but how fast each one is at being wrong.
#
# `n` is sized so a run is milliseconds and not microseconds: process startup
# dominates at small `n` and the number stops being about the loop.
BENCH = [
    dict(name="sum_to",
         n=300000,
         mojo="""def sum_to(n):
    s = 0
    i = 1
    while i <= n:
        s = s + i
        i = i + 1
    return s
""",
         c="""int bench(int n) {
    long long s = 0;
    for (int i = 1; i <= n; i++) s = s + i;
    return (int)(s & 0xff);
}
""",
         py="""def sum_to(n):
    s = 0
    i = 1
    while i <= n:
        s = s + i
        i = i + 1
    return s
"""),
    dict(name="fib_iter",
         n=200000,
         mojo="""def fib_iter(n):
    a = 0
    b = 1
    i = 0
    while i < n:
        t = a + b
        a = b
        b = t
        i = i + 1
    return a
""",
         c="""int bench(int n) {
    int a = 0, b = 1;
    for (int i = 0; i < n; i++) { int t = a + b; a = b; b = t; }
    return a & 0xff;
}
""",
         py="""def fib_iter(n):
    a = 0
    b = 1
    i = 0
    while i < n:
        t = a + b
        a = b
        b = t
        i = i + 1
    return a
"""),
    dict(name="gcd",
         n=70000,
         mojo="""def gcd(a):
    b = 6765
    while b != 0:
        t = a - (a / b) * b
        a = b
        b = t
    return a
""",
         c="""int bench(int a) {
    int b = 6765;
    while (b != 0) { int t = a - (a / b) * b; a = b; b = t; }
    return a & 0xff;
}
""",
         py="""def gcd(a):
    b = 6765
    while b != 0:
        t = a - (a // b) * b
        a = b
        b = t
    return a
"""),
    dict(name="collatz",
         n=250000,
         mojo="""def collatz(n):
    steps = 0
    while n != 1:
        if n % 2 == 0:
            n = n / 2
        else:
            n = 3 * n + 1
        steps = steps + 1
    return steps
""",
         c="""int bench(int n) {
    int steps = 0;
    while (n != 1) {
        if (n % 2 == 0) n = n / 2; else n = 3 * n + 1;
        steps = steps + 1;
    }
    return steps & 0xff;
}
""",
         py="""def collatz(n):
    steps = 0
    while n != 1:
        if n % 2 == 0:
            n = n // 2
        else:
            n = 3 * n + 1
        steps = steps + 1
    return steps
"""),
    dict(name="popcount",
         n=300000,
         mojo="""def popcount(n):
    total = 0
    i = 0
    while i < n:
        v = i
        while v != 0:
            total = total + (v % 2)
            v = v / 2
        i = i + 1
    return total
""",
         c="""int bench(int n) {
    int total = 0;
    for (int i = 0; i < n; i++) { int v = i; while (v != 0) { total += v % 2; v /= 2; } }
    return total & 0xff;
}
""",
         py="""def popcount(n):
    total = 0
    i = 0
    while i < n:
        v = i
        while v != 0:
            total = total + (v % 2)
            v = v // 2
        i = i + 1
    return total
"""),
    dict(name="triangular_nested",
         n=420,
         mojo="""def triangular_nested(n):
    total = 0
    i = 1
    while i <= n:
        j = 1
        while j <= i:
            total = total + j
            j = j + 1
        i = i + 1
    return total
""",
         c="""int bench(int n) {
    long long total = 0;
    for (int i = 1; i <= n; i++) for (int j = 1; j <= i; j++) total += j;
    return (int)(total & 0xff);
}
""",
         py="""def triangular_nested(n):
    total = 0
    i = 1
    while i <= n:
        j = 1
        while j <= i:
            total = total + j
            j = j + 1
        i = i + 1
    return total
"""),
]


def _sys_py() -> str:
    """The interpreter to call for the CPython column.

    `sys.executable`, NOT `python3` from `PATH`: the repository needs 3.10+
    (`str | None` annotations at module scope in `formal/types.py` are a
    hard `TypeError` on 3.9) and the `python3` a shell happens to resolve can
    be an older one than the one running this file. Using the running
    interpreter is the only way the CPython column is comparable to the two
    compiled columns at all.
    """
    return sys.executable


# ── counting ────────────────────────────────────────────────────────────────
def _count_arm64(code: bytes, info: dict) -> int:
    """Instructions in the CODE region of an arm64 image."""
    from formal.peephole import decode_arm64
    return _count_code_region(code, info, 4,
                              lambda off: decode_arm64(
                                  struct.unpack_from("<I", code, off)[0]))


def _count_x86(code: bytes, info: dict) -> int:
    """Instructions in the CODE region of an x86-64 image."""
    from formal.x86_64_decode import decode_all, decode_one
    base = info["base_addr"]
    start = info.get("func_offset", base) - base
    strs = [a for n, a in (info.get("labels") or {}).items() if n.startswith("str_")]
    end = (min(strs) - base) if strs else len(code)
    if end <= start:
        return 0
    n = 0
    off = start
    while off < end:
        try:
            insn = decode_one(code, off)
        except Exception:
            break
        off = insn.next_offset
        n += 1
    return n


def _count_code_region(code: bytes, info: dict, width: int, decode) -> int:
    base = info["base_addr"]
    strs = [a - base for n, a in (info.get("labels") or {}).items()
            if n.startswith("str_")]
    end = min(strs) if strs else len(code)
    n = 0
    for off in range(0, end - width + 1, width):
        if decode(off) is not None:
            n += 1
    return n


_COUNTER = {"arm64": _count_arm64, "x86_64": _count_x86}


def _count_c(binary: str, symbol: str) -> int:
    """Instructions in `symbol` of a Mach-O, as `otool -tV` prints them.

    `symbol` rather than "the whole image", because the comparison is between
    ONE FUNCTION written three ways and the entry stub is noise in all three.
    Counting the function's own lines also means the number is comparable to
    the other two columns, which count one function too.
    """
    out = subprocess.run(["otool", "-tV", binary], capture_output=True,
                         text=True, check=True).stdout
    inside = False
    n = 0
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if line.startswith(symbol + ":"):
            inside = True
            continue
        if inside:
            if line.endswith(":") and not line[0].isspace():
                break
            # An instruction line is "ADDR<tab>HEX<tab>mnemonic operands".
            parts = stripped.split("\t")
            if len(parts) >= 3 and parts[-1].strip():
                n += 1
    return n


# ── running ─────────────────────────────────────────────────────────────────
def _best_of(argv: list, runs: int, timeout: float = 300.0) -> dict:
    """Best (shortest) wall clock of `runs` executions, and the exit status."""
    best = None
    status = None
    for _ in range(runs):
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"wall_s": None, "exit": "timeout"}
        dt = time.perf_counter() - t0
        if best is None or dt < best:
            best = dt
        status = proc.returncode
    return {"wall_s": best, "exit": status}


def _formal_run_argv(path: str, arch: str) -> list:
    if arch == "x86_64" and sys.platform == "darwin":
        return ["arch", "-x86_64", path]
    return [path]


# ── the two halves ──────────────────────────────────────────────────────────
def census(opt: bool, quiet: bool = False) -> dict:
    """Per-program instruction counts over `formal/examples/*.mojo`."""
    import formal.build as B
    rows = []
    for src in sorted(glob.glob(os.path.join(ROOT, "formal", "examples", "*.mojo"))):
        row = {"program": os.path.relpath(src, ROOT)}
        for arch in ARCHES:
            out = os.path.join(tempfile.gettempdir(),
                               f"formal_bench_{arch}_{os.path.basename(src)}")
            try:
                r = B.compile_formal(src, output=out, prove=False, check=False,
                                     arch=arch, opt=opt)
                row[arch] = {"insns": _COUNTER[arch](r["code"], r["info"]),
                             "bytes": len(r["code"])}
            except Exception as e:                      # noqa: BLE001
                row[arch] = {"error": f"{type(e).__name__}: {e}"}
        rows.append(row)
    totals = {}
    for arch in ARCHES:
        totals[arch] = sum(r[arch].get("insns", 0) for r in rows)
    if not quiet:
        print(f"{'program':44s} {'arm64':>10s} {'x86_64':>10s}")
        for r in rows:
            cells = []
            for arch in ARCHES:
                v = r[arch]
                cells.append(f"{v['insns']:>10d}" if "insns" in v
                             else f"{'ERR':>10s}")
            print(f"{r['program']:44s} {cells[0]} {cells[1]}")
        print(f"{'TOTAL':44s} {totals['arm64']:>10d} {totals['x86_64']:>10d}")
    return {"rows": rows, "totals": totals}


def bench(opt: bool, runs: int, only: list = None) -> dict:
    """The three-way benchmark: this compiler, `gcc -O0`, CPython."""
    import formal.build as B
    out_rows = []
    for case in BENCH:
        if only and case["name"] not in only:
            continue
        row = {"name": case["name"], "n": case["n"], "impls": {}}
        answers = {}
        # ── this compiler, both backends ──
        for arch in ARCHES:
            with tempfile.TemporaryDirectory() as td:
                src = os.path.join(td, case["name"] + ".mojo")
                out = os.path.join(td, case["name"] + ".aout")
                with open(src, "w") as f:
                    f.write(case["mojo"])
                try:
                    r = B.compile_formal(src, output=out, prove=False,
                                         check=False, arch=arch, opt=opt,
                                         test_input=case["n"])
                    run = _best_of(_formal_run_argv(out, arch), runs)
                    answers[arch] = run["exit"]
                    row["impls"]["formal-" + arch] = {
                        "insns": _COUNTER[arch](r["code"], r["info"]),
                        "bytes": len(r["code"]),
                        "wall_s": run["wall_s"], "exit": run["exit"]}
                except Exception as e:                  # noqa: BLE001
                    row["impls"]["formal-" + arch] = {
                        "error": f"{type(e).__name__}: {e}"}
        # ── the host C compiler at -O0 ──
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, case["name"] + ".c")
            out = os.path.join(td, case["name"] + ".c.bin")
            with open(src, "w") as f:
                f.write("#include <stdio.h>\n" + case["c"] +
                        f"int main(void) {{ return bench({case['n']}); }}\n")
            cc = subprocess.run(["gcc", "-O0", "-o", out, src],
                                capture_output=True, text=True)
            if cc.returncode != 0:
                row["impls"]["gcc -O0"] = {"error": cc.stderr.strip()[:400]}
            else:
                run = _best_of([out], runs)
                answers["gcc"] = run["exit"]
                row["impls"]["gcc -O0"] = {
                    "insns": _count_c(out, "_bench"),
                    "wall_s": run["wall_s"], "exit": run["exit"]}
        # ── CPython ──
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, case["name"] + ".py")
            with open(src, "w") as f:
                f.write(case["py"] +
                        f"import sys\n"
                        f"sys.exit({case['name']}({case['n']}) & 0xff)\n")
            run = _best_of([_sys_py(), src], runs)
            answers["cpython"] = run["exit"]
            row["impls"]["cpython"] = {"wall_s": run["wall_s"],
                                       "exit": run["exit"]}
        vals = {k: v for k, v in answers.items() if isinstance(v, int)}
        row["agree"] = len(set(vals.values())) <= 1
        row["answers"] = vals
        out_rows.append(row)
        if not opt:
            _print_bench_row(row)
    return {"rows": out_rows, "opt": opt}


def _print_bench_row(row: dict) -> None:
    print(f"\n== {row['name']}  (n = {row['n']})")
    print(f"   {'implementation':18s} {'instructions':>12s} {'best wall':>11s}  exit")
    for name, v in row["impls"].items():
        if "error" in v:
            print(f"   {name:18s} {'ERROR':>12s} {'':>11s}  {v['error'][:60]}")
            continue
        ins = v.get("insns")
        ins_s = f"{ins:>12d}" if ins is not None else f"{'-':>12s}"
        w = v.get("wall_s")
        w_s = f"{w * 1000:>10.2f}m" if w is not None else f"{'-':>11s}"
        print(f"   {name:18s} {ins_s} {w_s}  {v.get('exit')}")
    print(f"   answers agree: {row['agree']}  {row['answers']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bench", action="store_true",
                    help="the three-way benchmark instead of the census")
    ap.add_argument("--opt", action="store_true",
                    help="build every program through the peephole pass")
    ap.add_argument("--runs", type=int, default=5,
                    help="executions per timed implementation (default 5)")
    ap.add_argument("--only", action="append", default=None,
                    help="benchmark case name, repeatable")
    ap.add_argument("--json", default=None, help="write the measurements here")
    args = ap.parse_args(argv)
    data = bench(args.opt, args.runs, args.only) if args.bench \
        else census(args.opt)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())