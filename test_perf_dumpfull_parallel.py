"""Regression test for PERF_dump_full_closure_is_single_threaded.

Dump-full now uses the parallel frozen-snapshot path by default; it must
produce a valid .ci for a module with imports.
"""
import subprocess, sys, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
FIRE = os.path.join(HERE, "fire.py")


def test_dump_full_parallel_default_with_imports():
    with tempfile.TemporaryDirectory() as td:
        helper_path = os.path.join(td, "helper.mojo")
        with open(helper_path, "w") as f:
            f.write("fn add(a: Int, b: Int) -> Int:\n    return a + b\n")
        src_path = os.path.join(td, "test_input.mojo")
        with open(src_path, "w") as f:
            f.write("from helper import add\n\ndef main():\n    print(add(1, 2))\n")

        r = subprocess.run([PYTHON, FIRE, "--dump-full", src_path],
                           capture_output=True, text=True, cwd=td)
        assert r.returncode == 0, f"dump-full failed: {r.stderr}"
        basename = os.path.splitext(os.path.basename(src_path))[0]
        ci_path = os.path.join(td, basename + ".ci")
        assert os.path.exists(ci_path)
        with open(ci_path, "rb") as f:
            ci = f.read()
        assert ci, "empty .ci produced"


if __name__ == "__main__":
    test_dump_full_parallel_default_with_imports()
