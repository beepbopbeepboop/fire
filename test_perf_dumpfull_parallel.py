"""Equivalence test for PERF_dump_full_closure_is_single_threaded.

Option (a): parallel parse + frozen-snapshot emission (steps 1-4).
C11 lock-free mmap queue deferred; multiprocessing.Pool used.
Acceptance: byte-identical .ci against serial path.
"""
import subprocess, sys, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
FIRE = os.path.join(HERE, "fire.py")


def _run_dump_full(src_path, serial=False):
    args = [PYTHON, FIRE, "--dump-full"]
    if serial:
        args.append("--serial")
    args.append(src_path)
    cwd = os.path.dirname(os.path.abspath(src_path))
    r = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    return r


def test_serial_vs_parallel_byte_identical():
    with tempfile.TemporaryDirectory() as td:
        helper_path = os.path.join(td, "helper.mojo")
        with open(helper_path, "w") as f:
            f.write("fn add(a: Int, b: Int) -> Int:\n    return a + b\n")
        src_path = os.path.join(td, "test_input.mojo")
        with open(src_path, "w") as f:
            f.write("from helper import add\n\ndef main():\n    print(add(1, 2))\n")

        # Serial
        r1 = subprocess.run([PYTHON, FIRE, "--dump-full", "--serial", src_path],
                            capture_output=True, text=True, cwd=td)
        assert r1.returncode == 0, f"serial failed: {r1.stderr}"
        basename = os.path.splitext(os.path.basename(src_path))[0]
        serial_ci = os.path.join(td, basename + ".ci")
        assert os.path.exists(serial_ci)
        with open(serial_ci, "rb") as f:
            serial_bytes = f.read()

        # Parallel
        r2 = subprocess.run([PYTHON, FIRE, "--dump-full", src_path],
                            capture_output=True, text=True, cwd=td)
        assert r2.returncode == 0, f"parallel failed: {r2.stderr}"
        with open(serial_ci, "rb") as f:
            parallel_bytes = f.read()

        assert serial_bytes == parallel_bytes, "serial and parallel dump-full outputs differ"


if __name__ == "__main__":
    test_serial_vs_parallel_byte_identical()
