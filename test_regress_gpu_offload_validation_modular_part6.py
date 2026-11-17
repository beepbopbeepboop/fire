"""Part 6: the compiled path must refuse an under-supplied specialization.

`bugs/GPU_offload_validation_modular-part6.md` (parent:
`bugs/hard/GPU_offload_validation_modular.md`, row
`compile_offload_unbound_param_error.mojo`).

`fire.py run` (part 5) raises a Python traceback on this probe today;
`fire.py <file>` / `fire.py build` builds a binary that prints `0` at exit 0,
which is a silent wrong answer. The control probe (both specialization
arguments supplied) prints `6` on the same path, so the `0` is the
under-supplied instantiation and not the nested-bracket stub bug.

`fire.py build` is used rather than `fire.py <file>` on purpose: the bare form
falls back to the interpreter when the compile fails, so a diagnostic printed
by the interpreter would make this test pass without the compiled path ever
refusing. Building and then running the binary cannot fall back.

Cost: two link-mode builds of a 10-line program, measured 27-136 s for both
and 0.1-0.3 GB peak (the stdlib closure dominates when the compiler cache
misses).
Quick test: this file only.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from exec_budget import BUILD_TIMEOUT, RUN_TIMEOUT


ROOT = Path(__file__).resolve().parent

UNDER_SUPPLIED = '''def param_fn[x: Int, y: Int](a: Int) -> Int:
    return a + x + y


def main():
    print(param_fn[2](1))
'''

FULLY_SUPPLIED = '''def param_fn[x: Int, y: Int](a: Int) -> Int:
    return a + x + y


def main():
    print(param_fn[2, 3](1))
'''


def _build_and_run(src: str, stem: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Build `src` with `fire.py build -o <tmp bin>`, then run the binary.

    Returns the BUILD's result and the binary path; the caller runs the
    binary only when the build succeeded (a refused build produces nothing to
    run, which is the point of the refusal).
    """
    (ROOT / ".tmp").mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".mojo", delete=False, dir=ROOT / ".tmp"
    ) as f:
        f.write(src)
        path = Path(f.name)
    binary = ROOT / ".tmp" / stem
    # A stale binary from an earlier run would survive a refused build and
    # make "a refused build produced no binary" pass for the wrong reason.
    binary.unlink(missing_ok=True)
    try:
        built = subprocess.run(
            [
                sys.executable,
                "tools/memslot.py",
                "--gb",
                "8",
                "--label",
                stem,
                "--",
                sys.executable,
                "fire.py",
                "build",
                "-o",
                str(binary),
                str(path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT,
        )
        return built, binary
    finally:
        path.unlink(missing_ok=True)


def _run_binary(binary: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=RUN_TIMEOUT
    )


class TestUnboundSpecializationParameterCompiled(unittest.TestCase):
    def test_under_supplied_bracket_refused_at_build(self) -> None:
        built, binary = _build_and_run(UNDER_SUPPLIED, "gpu-part6-unbound")
        try:
            combined = built.stdout + built.stderr
            self.assertNotEqual(
                built.returncode,
                0,
                msg=f"the build accepted an under-supplied specialization\n"
                f"stdout:\n{built.stdout}\nstderr:\n{built.stderr}",
            )
            self.assertIn(
                "failed to infer parameter",
                combined,
                msg=f"missing the canonical diagnostic\nstdout:\n{built.stdout}\nstderr:\n{built.stderr}",
            )
            self.assertIn(
                "'y'",
                combined,
                msg=f"diagnostic does not name the unbound parameter\nstdout:\n{built.stdout}\nstderr:\n{built.stderr}",
            )
            self.assertIn(
                "param_fn",
                combined,
                msg=f"diagnostic does not name the callee\nstdout:\n{built.stdout}\nstderr:\n{built.stderr}",
            )
            # A refused build must not leave a binary that answers 0.
            self.assertFalse(
                binary.exists(), msg=f"a refused build produced {binary}"
            )
        finally:
            binary.unlink(missing_ok=True)

    def test_fully_supplied_bracket_still_builds_and_runs(self) -> None:
        built, binary = _build_and_run(FULLY_SUPPLIED, "gpu-part6-control")
        try:
            self.assertEqual(
                built.returncode,
                0,
                msg=f"the control build failed\nstdout:\n{built.stdout}\nstderr:\n{built.stderr}",
            )
            self.assertTrue(binary.exists(), msg=f"no binary at {binary}")
            ran = _run_binary(binary)
            self.assertEqual(
                ran.returncode,
                0,
                msg=f"the control binary failed\nstdout:\n{ran.stdout}\nstderr:\n{ran.stderr}",
            )
            self.assertIn("6", ran.stdout)
        finally:
            binary.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
