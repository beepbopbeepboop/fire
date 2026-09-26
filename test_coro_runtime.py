#!/usr/bin/env python3
"""test_coro_runtime.py -- builds and runs the standalone C unit tests for
the A3 stack-switch coroutine runtime (doc/COROUTINE.html):

  Layer 3 (SEAM B, context switch)  : runtime/test_fire_coro_ctx.c
  Layer 2 (SEAM A, coroutine runtime): runtime/test_fire_coro.c

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

# (name, test .c, extra .c deps, extra cc flags)
TESTS = [
    ('layer3-ctx', 'test_fire_coro_ctx.c', [], ()),
    ('layer2-coro', 'test_fire_coro.c',
     ['fire_coro.c', 'test_fire_coro_exc_stub.c'], ()),
    # `layer1-shim` and `future-event` are the two cases that link
    # fire_coro_gen.c, and they are the odd ones out: they link the REAL
    # fire_runtime.c and therefore must NOT link
    # test_fire_coro_exc_stub.c, which is a standalone reimplementation of
    # exactly the runtime symbols (`_mojo_exc_*`, `_mojo_list_get_int`,
    # ...) that fire_coro.c calls — scaffolding whose own header comment
    # says it exists "so the Layer 2 unit test links without dragging in
    # fire_runtime.c". Linking both is 14 duplicate symbols. They need the
    # real runtime because fire_coro_gen.c's TAGGED-value path
    # (tagged_int/word/str/list/dyn) reaches `mojo_list_len`, which it
    # declares `extern` and only fire_runtime.c defines — and the linker
    # pulls that path in whole whether or not the test exercises it, so
    # `layer1-shim` needs it for the same reason `future-event` does even
    # though only the latter drives tagged values at RUNTIME. The other
    # three link the stub and no runtime.
    #
    # Hence also the per-case `-std=gnu23` on those two: fire_runtime.c
    # declares `int mojo_type(...)`, which is C23 syntax (pre-C23 it
    # required a named parameter before the ellipsis). GCC takes it as a
    # GNU extension in its default gnu17 mode — which is why the real
    # build, compiled by gcc, has never noticed — but clang rejects it at
    # every -std below gnu23, and this test's default CC is `cc`, i.e.
    # clang on macOS. Scoped to the two cases that need it: the other
    # three compile clean under the default today and C23 has real
    # semantic changes, so there is no reason to move them.
    ('layer1-shim', 'test_fire_coro_gen.c',
     ['fire_coro_gen.c', 'fire_async_sched.c', 'fire_coro.c',
      'fire_runtime.c'],
     ('-std=gnu23',)),
    ('async-sched', 'test_fire_async_sched.c',
     ['fire_async_sched.c', 'fire_coro.c', 'test_fire_coro_exc_stub.c'], ()),
    ('future-event', 'test_fire_future.c',
     ['fire_coro_gen.c', 'fire_async_sched.c', 'fire_coro.c',
      'fire_runtime.c'],
     ('-std=gnu23',)),
]

# Layer 3 backends to validate.
BACKENDS = ['fire_coro_ctx_generic.c']
_mach = platform.machine().lower()
if _mach in ('arm64', 'aarch64'):
    BACKENDS.insert(0, 'fire_coro_ctx_aarch64.S')
# (x86_64 .S lands in Phase 5)


def _run(name, test_c, deps, backend, opt, wd, flags=()):
    out = os.path.join(wd, 'run')
    srcs = [os.path.join(RT, test_c)] + [os.path.join(RT, d) for d in deps]
    srcs.append(os.path.join(RT, backend))
    cmd = [CC, opt, '-w', '-I', RT] + list(flags) + ['-o', out] + srcs
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
        for name, test_c, deps, flags in TESTS:
            for backend in BACKENDS:
                for opt in ('-O0', '-O2'):
                    total += 1
                    ok, msg = _run(name, test_c, deps, backend, opt, wd,
                                   flags)
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
