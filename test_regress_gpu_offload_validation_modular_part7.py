"""Regression: `std.compile.compile_info` must refuse an unsliceable kernel.

Covers the `compile_offload_missing_symbol_error.mojo` case: a statically named
module-level kernel is accepted, while a computed kernel -- a runtime function
pointer (`get_fn[False]()`) or a parametrized reference (`get_fn[False]`) -- is
refused with `cannot slice out exported symbol`, not silently stubbed to 0.
Only the call form names the sliced symbol (`scale`); the parametrized
reference names the parameterized callee it mentions (`get_fn`).

Quick test: this file only (three interpreter runs, ~3 s, < 0.1 GB).
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from exec_budget import RUN_TIMEOUT


ROOT = Path(__file__).resolve().parent

STATIC_KERNEL = '''from std.compile import compile_info


def scale(x: Int) -> Int:
    return x * 3


def main():
    compile_info[scale, emission_kind="llvm"]()
    print(3)
'''

RUNTIME_POINTER_KERNEL = '''from std.compile import compile_info


def scale(x: Int) -> Int:
    return x * 3


def get_fn[flag: Bool]():
    return scale


def main():
    compile_info[get_fn[False](), emission_kind="llvm"]()
    print(0)
'''

PARAMETRIZED_REFERENCE_KERNEL = '''from std.compile import compile_info


def scale(x: Int) -> Int:
    return x * 3


def get_fn[flag: Bool]():
    return scale


def main():
    compile_info[get_fn[False], emission_kind="llvm"]()
    print(0)
'''


def _run(src: str, label: str) -> subprocess.CompletedProcess[str]:
    (ROOT / ".tmp").mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".mojo", delete=False, dir=ROOT / ".tmp"
    ) as f:
        f.write(src)
        path = Path(f.name)
    try:
        return subprocess.run(
            [
                sys.executable,
                "tools/memslot.py",
                "--gb",
                "8",
                "--label",
                label,
                "--",
                sys.executable,
                "fire.py",
                "run",
                str(path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
        )
    finally:
        path.unlink(missing_ok=True)


class TestCompileInfoExportedSymbol(unittest.TestCase):
    def test_static_kernel_is_accepted(self) -> None:
        r = _run(STATIC_KERNEL, "gpu-part7-static")
        self.assertEqual(
            r.returncode, 0, msg=f"expected success\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
        self.assertIn("3", r.stdout)

    def test_runtime_function_pointer_kernel_is_refused(self) -> None:
        r = _run(RUNTIME_POINTER_KERNEL, "gpu-part7-runtime")
        combined = r.stdout + r.stderr
        self.assertNotEqual(
            r.returncode, 0, msg=f"expected refusal\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
        self.assertIn(
            "cannot slice out exported symbol",
            combined,
            msg=f"missing the canonical diagnostic\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        self.assertIn(
            "scale",
            combined,
            msg=f"diagnostic does not name the symbol\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        self.assertNotIn(
            "Traceback (most recent call last)",
            combined,
            msg=f"an internal traceback is not a diagnostic\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )

    def test_parametrized_reference_kernel_is_refused(self) -> None:
        # `get_fn[False]` (no call) is still a computed kernel: the bracket
        # names a specialization, not a symbol that can be sliced out.
        r = _run(PARAMETRIZED_REFERENCE_KERNEL, "gpu-part7-paramref")
        combined = r.stdout + r.stderr
        self.assertNotEqual(
            r.returncode, 0, msg=f"expected refusal\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
        self.assertIn(
            "cannot slice out exported symbol",
            combined,
            msg=f"missing the canonical diagnostic\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        self.assertNotIn(
            "Traceback (most recent call last)",
            combined,
            msg=f"an internal traceback is not a diagnostic\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
