#!/usr/bin/env python3
"""Regression: `asyncio.run(main())` at module scope drove an uninitialised
pointer and failed with "a coroutine was expected".

The bridge's temp was a module-level VarDecl. The module-global pre-scan
recorded its store as a `_root_globals` field while `_toplevel` declared a
separate local and read that, so the driver received garbage. Each case is a
whole program; the compiled binary's stdout must equal what CPython prints for
the same source, and the expectation comes from running CPython on that source.
"""
import subprocess, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))

CASES = {
    "plain_main": '''\
import asyncio

async def main():
    print(7)

asyncio.run(main())
''',
    "variadic_aexit_awaited_in_main": '''\
import asyncio

class Box:
    async def __aexit__(self, *exc_details):
        n = 0
        for x in exc_details:
            n = n + 1
        return n

async def main():
    b = Box()
    r = await b.__aexit__(1, 2, 3)
    print(r)

asyncio.run(main())
''',
}


def cpython_stdout(src):
    r = subprocess.run([sys.executable, '-c', src], capture_output=True, text=True)
    return r.stdout


def main():
    tmp = os.path.join(HERE, '.tmp')
    os.makedirs(tmp, exist_ok=True)
    failures = 0
    for name, src in CASES.items():
        drv = os.path.join(tmp, f'asyncio_run_{name}.py')
        with open(drv, 'w') as f:
            f.write(src)
        exe = drv[:-len('.py')]
        # A binary left by an earlier run must not stand in for this build.
        if os.path.exists(exe):
            os.remove(exe)
        b = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build', drv, '-o', exe],
                           capture_output=True, text=True)
        if b.returncode != 0 or not os.path.exists(exe):
            print(f'FAIL {name}: build (exit {b.returncode})\n',
                  (b.stdout + b.stderr)[-1500:])
            failures += 1
            continue
        run = subprocess.run([exe], capture_output=True, text=True)
        want = cpython_stdout(src)
        if run.returncode != 0 or run.stdout != want:
            print(f'FAIL {name}: stdout {run.stdout!r} (exit {run.returncode}), '
                  f'CPython {want!r}')
            if run.stderr:
                print(run.stderr[-500:])
            failures += 1
            continue
        print(f'PASS {name}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
