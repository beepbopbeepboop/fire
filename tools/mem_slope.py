#!/usr/bin/env python3
"""Measure a leak SLOPE (bytes/iteration) for a compiled Mojo program.

doc/MEMORY.html §8 ("How to verify a memory change") is explicit that a single
size proves nothing: "Write the loop at two sizes (e.g. 100k and 400k) and
compare maximum resident set size. A flat pair is not leaking; a slope is
B/iter." That is what this does, and it also enforces the two other rules from
the same section that are easy to get wrong:

  * "Delete the previous binary before each build. A failed build that leaves a
    stale executable makes a broken loop look like a passing '0 B/iter' row."
    Every build here unlinks its output first, and treats a nonzero gcc exit as
    a measurement FAILURE rather than proceeding to run whatever is on disk.

  * "unchanged program output" is part of the evidence for a memory change, so
    stdout is captured at both sizes and compared; a slope with changing output
    is reported as FAIL, because that is a wrong-value bug wearing a leak's
    clothes.

Usage:
    python3 tools/mem_slope.py <file.mojo> [--sizes 100000,400000] [--label NAME]

The source must print nothing that varies with the iteration count; the tool
substitutes the iteration count for `MEM_SLOPE_N` if present, else passes it as
argv[1].

Example:
    python3 tools/mem_slope.py build/memprobes/boxed_capture.mojo
"""
import argparse
import os
import re
import resource
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from build_config import find_gcc          # noqa: E402
from gimple_codegen import compile_to_gimple  # noqa: E402


def substitute_n(src: str, n: int) -> str:
    """Replace the `MEM_SLOPE_N` placeholder with the iteration count `n`.

    A placeholder rather than argv so the probe program needs no argument
    handling, and a REQUIRED one: a probe with no placeholder would be measured
    at the same size twice, and "the peak did not change between two runs of the
    identical binary" is not evidence of anything.
    """
    if 'MEM_SLOPE_N' not in src:
        raise RuntimeError(
            'probe source has no MEM_SLOPE_N placeholder, so both sizes would '
            'compile the same program and the measurement would be vacuous')
    return re.sub(r'\bMEM_SLOPE_N\b', str(n), src)


def build(src_path: str, n: int) -> str:
    """Compile `src_path` at iteration count `n`; return the executable path.

    The count is substituted into the source text (see `substitute_n`), so each
    size is its own binary and the program's own literal is what changes — no
    dependence on the Mojo program being able to read argv.

    Raises on any build failure — a silent fall-through to a stale binary is
    the exact failure mode §8 calls out, so this never returns a path it did
    not just produce.
    """
    from gimple_codegen import compile_to_gimple

    src = open(src_path).read()
    src = substitute_n(src, n)
    c_code = compile_to_gimple(src, filename=src_path)

    tmp = tempfile.mkdtemp(prefix='memslope_')
    c_file = os.path.join(tmp, 'prog.c')
    exe_file = os.path.join(tmp, 'prog.exe')
    # Belt and braces with mkdtemp: if anything below reuses a fixed name, the
    # unlink still happens first.
    for p in (c_file, exe_file):
        if os.path.exists(p):
            os.unlink(p)
    with open(c_file, 'w') as f:
        f.write(c_code)

    runtime_dir = os.path.join(HERE, 'runtime')
    sources = [c_file, os.path.join(runtime_dir, 'fire_runtime.c')]
    if '__mgco_' in c_code or '__mojo_coro_yield_i' in c_code:
        import platform as _plat
        arch = ('fire_coro_ctx_aarch64.S'
                if _plat.machine().lower() in ('arm64', 'aarch64')
                else 'fire_coro_ctx_generic.c')
        for cs in ('fire_coro_gen.c', 'fire_coro.c', 'fire_async_sched.c', arch):
            sources.append(os.path.join(runtime_dir, cs))

    r = subprocess.run([find_gcc(), '-fgimple', f'-I{runtime_dir}',
                        '-o', exe_file, *sources],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(exe_file):
        raise RuntimeError(f'build failed (rc={r.returncode}):\n'
                           f'{r.stderr[-3000:]}')
    return exe_file


def run_at(exe: str) -> tuple[int, str, int]:
    """(peak_rss_bytes, stdout, returncode) for one run of `exe`."""
    # Fresh interpreter per measurement so RUSAGE_CHILDREN reports THIS run's
    # child peak, not a max over every child this process has ever spawned.
    probe = (
        "import resource, subprocess, sys\n"
        "r = subprocess.run([sys.argv[1]], capture_output=True,"
        " timeout=600)\n"
        "sys.stdout.buffer.write(r.stdout)\n"
        "sys.stderr.write(str(resource.getrusage(resource.RUSAGE_CHILDREN)"
        ".ru_maxrss))\n"
        "sys.stderr.write(' ' + str(r.returncode))\n"
    )
    r = subprocess.run([sys.executable, '-c', probe, exe],
                       capture_output=True, timeout=700)
    err = r.stderr.decode('utf-8', 'replace').strip().split()
    # The probe writes "<maxrss> <rc>" LAST on stderr, and the child's own
    # stderr is captured (not inherited), so the final two tokens are ours.
    # Anything else means the probe itself failed — surface it rather than
    # crashing on int('Traceback'), which would hide the real reason.
    if len(err) < 2 or not err[-2].isdigit() or not err[-1].lstrip('-').isdigit():
        raise RuntimeError(
            f'measurement probe failed for {exe}:\n'
            f'  stdout: {r.stdout.decode("utf-8", "replace")[-800:]!r}\n'
            f'  stderr: {r.stderr.decode("utf-8", "replace")[-2000:]!r}')
    maxrss, rc = int(err[-2]), int(err[-1])
    # macOS reports ru_maxrss in BYTES; Linux in KILOBYTES.
    rss_bytes = maxrss if sys.platform == 'darwin' else maxrss * 1024
    return rss_bytes, r.stdout.decode('utf-8', 'replace'), rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('--sizes', default='100000,400000')
    ap.add_argument('--label', default=None)
    a = ap.parse_args()

    sizes = [int(x) for x in a.sizes.split(',')]
    if len(sizes) != 2 or sizes[1] <= sizes[0]:
        print('need exactly two sizes, ascending', file=sys.stderr)
        return 2
    label = a.label or os.path.basename(a.src)

    try:
        results = []
        exes = []
        for n in sizes:
            exe = build(a.src, n)
            exes.append(exe)
            rss, out, rc = run_at(exe)
            results.append((n, rss, out, rc))
            print(f'  n={n:<9d} peak {rss / (1024*1024):8.2f} MB  rc={rc}'
                  f'  stdout {out[:60]!r}')

        (n0, rss0, out0, rc0), (n1, rss1, out1, rc1) = results
        if rc0 != 0 or rc1 != 0:
            print(f'FAIL {label}: nonzero exit ({rc0}, {rc1})')
            return 1
        if out0 != out1:
            print(f'FAIL {label}: output differs between sizes — a wrong-value '
                  f'bug, not just a leak:\n  {out0[:200]!r}\n  {out1[:200]!r}')
            return 1
        slope = (rss1 - rss0) / (n1 - n0)
        verdict = 'flat' if abs(slope) < 0.5 else f'{slope:+.2f} B/iter'
        print(f'{label}: {verdict}   '
              f'(delta {(rss1 - rss0) / (1024*1024):+.2f} MB over '
              f'{n1 - n0} iterations)')
        if slope >= 0.5:
            print(f'LEAK {label}: {slope:+.2f} B/iter')
            return 1
        return 0
    finally:
        for e in exes:
            try:
                os.unlink(e)
            except OSError:
                pass


if __name__ == '__main__':
    sys.exit(main())