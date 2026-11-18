#!/usr/bin/env python3
"""`list.extend` on a list whose per-slot kinds came from `append_word`.

A list built by appending a tagged word -- the loop variable of a kind-mixed
generator, `for v in g(): out.append(v)` -- has its per-slot kinds in
`_list_word_push`'s growable buffer: `_KindRow.kinds` points EIGHT BYTES INTO
a malloc'd block whose header holds the capacity (`owned == 2`). Every other
kinds buffer is either shared (`owned == 0`) or a plain malloc'd buffer
(`owned == 1`). `_kinds_append` treated anything with `owned` set as plain and
called `realloc()` on that interior pointer, which aborts the process:

    malloc: *** error for object 0x...: pointer being freed was not allocated
    ... _realloc <- mojo_list_extend <- _gimple_main

So `b.extend(a)` crashed whenever BOTH lists had been fed by `append_word`,
and no `print` ran. The compiler's own closure walk does exactly this --
`_gmi_all_stmts_nonfunc` appends each statement to `result` and then
`result.extend`s its recursive call's list -- which is why the self-hosted
binary aborted while dumping `bootstrap_test_advanced.mojo` (the stage2 /
stage3 `bootstrap-stage*-dumps` red).

The regression is asserted on the ACTUAL output of a compiled program, linked
against `runtime/fire_runtime.c` directly (the same single-TU path the
bootstrap gcc step uses, no `build_stdlib_dylib` dylib in the way), and the
answer is CPython's on the same text.

Run:  python3 test_regress_list_extend_owned_kinds.py [-v] [--keep]
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')


def _p(*lines: str) -> str:
    return "\n".join(lines) + "\n"


# Both lists are built with `append_word` (a `v` whose kind is not known
# statically), then the second extends the first. CPython: [1, 'x', 1, 'x'].
CASES = [
    ("extend-into-an-append-word-list", _p(
        "def g():",
        "    yield 1",
        '    yield "x"',
        "",
        "def main():",
        "    a = []",
        "    for v in g():",
        "        a.append(v)",
        "    b = []",
        "    for v in g():",
        "        b.append(v)",
        "    b.extend(a)",
        "    print(b)",
        "",
        "main()")),
    # The destination is described by `append_word` and the source by an
    # ordinary typed literal, so the appended kinds are concatenated onto the
    # growable buffer instead of replacing it.
    ("extend-a-typed-list-into-an-append-word-list", _p(
        "def g():",
        "    yield 1",
        '    yield "x"',
        "",
        "def main():",
        "    b = []",
        "    for v in g():",
        "        b.append(v)",
        '    b.extend([2, "y"])',
        "    print(b)",
        "",
        "main()")),
]


def run_cpython(src: str, tmp: str):
    path = os.path.join(tmp, "ref.py")
    with open(path, "w") as f:
        f.write(src + "\n")
    p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT_S)
    return p.stdout, p.returncode, p.stderr


def run_compiled(src: str, tmp: str, name: str):
    from build_config import find_gcc
    from gimple_codegen import compile_to_gimple

    c = compile_to_gimple(src)
    c_file = os.path.join(tmp, name + ".c")
    exe = os.path.join(tmp, name)
    with open(c_file, "w") as f:
        f.write(c)
    sources = [c_file, os.path.join(RUNTIME, "fire_runtime.c")]
    if "__mgco_" in c or "__mojo_coro_yield_i" in c:
        arch = ("fire_coro_ctx_aarch64.S"
                if platform.machine().lower() in ("arm64", "aarch64")
                else "fire_coro_ctx_generic.c")
        sources += [os.path.join(RUNTIME, x) for x in
                    ("fire_coro_gen.c", "fire_coro.c", "fire_async_sched.c",
                     arch)]
    r = subprocess.run([find_gcc(), "-fgimple", "-I" + RUNTIME, "-o", exe,
                        *sources], capture_output=True, text=True,
                       timeout=COMPILE_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError("generated C rejected by gcc -fgimple:\n"
                           + r.stderr[-3000:])
    p = subprocess.run([exe], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT_S)
    return p.stdout, p.returncode, p.stderr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print every case, not just failures")
    ap.add_argument("--keep", action="store_true",
                    help="keep the generated C and binaries")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="liste-", dir=HERE)
    passed = failed = 0
    try:
        for name, src in CASES:
            want_out, want_rc, want_err = run_cpython(src, tmp)
            if want_rc != 0 or want_err.strip():
                print(f"BROKEN {name}: the CPython reference itself failed")
                print(want_err[-800:])
                failed += 1
                continue
            try:
                got_out, got_rc, _got_err = run_compiled(src, tmp, name)
            except subprocess.TimeoutExpired:
                print(f"FAIL {name}: compiled program did not finish")
                failed += 1
                continue
            except RuntimeError as e:
                print(f"FAIL {name}: {e}")
                failed += 1
                continue
            if got_rc != want_rc or got_out != want_out:
                failed += 1
                print(f"FAIL {name}: compiled exit {got_rc}, cpython "
                      f"exit {want_rc}")
                print(f"      cpython {want_out!r}")
                print(f"      compiled {got_out!r}")
            else:
                passed += 1
                if args.verbose:
                    print(f"ok   {name}: {got_out.strip()}")
    finally:
        if not args.keep:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"{passed} passed, {failed} failed"
          + ("" if passed + failed == len(CASES) else
             f" ({len(CASES)} cases)"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
