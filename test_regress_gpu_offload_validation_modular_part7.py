"""Part 7: `compile_info` must refuse a kernel it cannot slice out as a symbol.

`bugs/GPU_offload_validation_modular-part7.md` (parent:
`bugs/hard/GPU_offload_validation_modular.md`, row
`compile_offload_missing_symbol_error.mojo`).

Today `std.compile` is not shimmed, so it falls through to the generic `std.*`
auto-stub (`_AutoStubNamespace`): `compile_info[...]()` answers `0` for a real
module-level kernel AND for a runtime function pointer (`get_fn[False]()`),
and the program exits 0 either way. The canonical Modular case requires the
second one to be refused with `cannot slice out exported symbol ... scale ...`.

The first probe is the control: a kernel named statically is sliceable and must
keep working.

Quick test: this file only (two interpreter runs, ~2 s, < 0.1 GB).
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


if __name__ == "__main__":
    unittest.main()
