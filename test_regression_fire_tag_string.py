#!/usr/bin/env python3
"""Regression for the self-hosted binary segfaulting in _canon_int: a heap
string's bytes read back as a struct type tag (type(node) on a str node, then a
dict-key lookup on it).

Verifies that mojo_read_type_tag_safe rejects a boxed string (returns 0)
so the self-hosted binary does not segfault on dict-key lookup.
"""
import subprocess, sys, tempfile, os
HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    # The C regression lives in runtime/test_fire_coro_gen.c.
    # We compile and run layer1-shim (links the real fire_runtime.c).
    rt = os.path.join(HERE, 'runtime')
    with tempfile.TemporaryDirectory() as wd:
        out = os.path.join(wd, 'run')
        cmd = [
            'cc', '-O0', '-w', '-I', rt,
            '-std=gnu23',
            '-o', out,
            os.path.join(rt, 'test_fire_coro_gen.c'),
            os.path.join(rt, 'fire_coro_gen.c'),
            os.path.join(rt, 'fire_async_sched.c'),
            os.path.join(rt, 'fire_coro.c'),
            os.path.join(rt, 'fire_coro_ctx_generic.c'),
            os.path.join(rt, 'fire_runtime.c'),
        ]
        cp = subprocess.run(cmd, capture_output=True, text=True)
        assert cp.returncode == 0, f"compile failed: {cp.stderr}"
        cp = subprocess.run([out], capture_output=True, text=True, timeout=60)
        ok = cp.returncode == 0
        msg = (cp.stdout + cp.stderr).strip()
        if ok:
            print(f"PASS: regression tag-string test ok | {msg}")
        else:
            print(f"FAIL: regression tag-string test | {msg}")
        return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
