#!/usr/bin/env python3
"""test_coro_runtime.py -- builds and runs the standalone C unit tests for
the A3 stack-switch coroutine runtime (doc/COROUTINE.html):

  Layer 3 (SEAM B, context switch)  : runtime/test_mojo_coro_ctx.c
  Layer 2 (SEAM A, coroutine runtime): runtime/test_mojo_coro.c

Each is run against BOTH Layer 3 backends (the aarch64 .S and the ucontext
generic fallback) at -O0 and -O2. All four combinations per test must pass
identically -- the .S files are validated against the generic oracle here.
"""
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RT = os.path.join(HERE, 'runtime')

CC = os.environ.get('CC', 'cc')

# (name, test .c, extra .c deps)
TESTS = [
    ('layer3-ctx', 'test_mojo_coro_ctx.c', []),
    ('layer2-coro', 'test_mojo_coro.c', ['mojo_coro.c', 'test_mojo_coro_exc_stub.c']),
    ('layer1-shim', 'test_mojo_coro_gen.c',
     ['mojo_coro_gen.c', 'mojo_coro.c', 'test_mojo_coro_exc_stub.c']),
    ('async-sched', 'test_mojo_async_sched.c',
     ['mojo_async_sched.c', 'mojo_coro.c', 'test_mojo_coro_exc_stub.c']),
]

# Layer 3 backends to validate.
BACKENDS = ['mojo_coro_ctx_generic.c']
_mach = platform.machine().lower()
if _mach in ('arm64', 'aarch64'):
    BACKENDS.insert(0, 'mojo_coro_ctx_aarch64.S')
# (x86_64 .S lands in Phase 5)


def _run(name, test_c, deps, backend, opt, wd):
    out = os.path.join(wd, 'run')
    srcs = [os.path.join(RT, test_c)] + [os.path.join(RT, d) for d in deps]
    srcs.append(os.path.join(RT, backend))
    cmd = [CC, opt, '-w', '-I', RT, '-o', out] + srcs
    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0:
        return False, f'compile failed:\n{cp.stderr}'
    cp = subprocess.run([out], capture_output=True, text=True, timeout=60)
    ok = cp.returncode == 0
    return ok, (cp.stdout + cp.stderr).strip()


def main():
    fails = 0
    total = 0
    with tempfile.TemporaryDirectory() as wd:
        for name, test_c, deps in TESTS:
            for backend in BACKENDS:
                for opt in ('-O0', '-O2'):
                    total += 1
                    ok, msg = _run(name, test_c, deps, backend, opt, wd)
                    tag = f'{name:12s} {backend:24s} {opt}'
                    if ok:
                        print(f'PASS  {tag}  | {msg}')
                    else:
                        fails += 1
                        print(f'FAIL  {tag}\n{msg}')
    print(f'\n{total - fails}/{total} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
