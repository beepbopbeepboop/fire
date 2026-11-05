"""Regression/pinning test for FORMAL_binary_heap_mojo_after_the_len_value.

The binary heap stdlib module now builds in the formal pipeline (rows 0,0a,1 fixed).
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(ROOT, "..", "new-modular", "Mojo", "stdlib", "std", "collections", "binary_heap.mojo")
OUT = os.path.join(ROOT, ".tmp", "bh_pinned.out")


def test_binary_heap_mojo_builds_formally():
    os.makedirs(os.path.join(ROOT, ".tmp"), exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    cmd = [sys.executable, "fire.py", "build", "--formal", "--no-prove", "--backend=arm64",
           "-o", OUT, REF]
    r = subprocess.run(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert r.returncode == 0, f"failed: {r.stderr.decode()}"
    assert b"Built:" in r.stdout or os.path.exists(OUT), r.stdout.decode()
