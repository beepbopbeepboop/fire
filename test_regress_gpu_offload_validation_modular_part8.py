"""Part 8: refuse conversion/operation on an unsupported float8 dtype.

`bugs/GPU_offload_validation_modular-part8.md` (parent:
`bugs/hard/GPU_offload_validation_modular.md`, row
`op_with_unsupported_type_error.mojo`, host half).

Today the float8 family does not exist in the interpreter (`DType` is a
SimpleNamespace with int/uint/float16-64/bfloat16/bool), so
`DType.float8_e3m4` raises `AttributeError`; a program spelling
`Float8_e3m4` as an annotation is accepted and `var b: Float32 = a` silently
copies the value (`1.0`, exit 0). The canonical Modular case wants
`conversion from 'f8e3m4' to 'f32' is not implemented` and
`operation with a type 'f8e3m4' is not implemented`.

Quick test: this file only (three interpreter runs, ~3 s, < 0.1 GB).
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from exec_budget import RUN_TIMEOUT


ROOT = Path(__file__).resolve().parent

SIZE_OF_PROBE = '''def main():
    print(size_of[DType.float8_e3m4]())
'''

CONVERSION_PROBE = '''def main():
    var a: Float8_e3m4 = 1.0
    var b: Float32 = a
    print(b)
'''

OPERATION_PROBE = '''def main():
    var a: Float8_e3m4 = 1.0
    var b: Float8_e3m4 = 2.0
    print(a + b)
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


class TestUnsupportedFloat8Dtype(unittest.TestCase):
    def test_float8_family_exists_with_width_one(self) -> None:
        r = _run(SIZE_OF_PROBE, "gpu-part8-sizeof")
        combined = r.stdout + r.stderr
        self.assertEqual(
            r.returncode, 0, msg=f"expected success\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
        self.assertIn(
            "1", combined, msg=f"float8_e3m4 is one byte\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )

    def test_conversion_to_f32_is_refused(self) -> None:
        r = _run(CONVERSION_PROBE, "gpu-part8-convert")
        combined = r.stdout + r.stderr
        self.assertNotEqual(
            r.returncode, 0, msg=f"expected refusal\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
        self.assertIn(
            "conversion from 'f8e3m4' to 'f32' is not implemented",
            combined,
            msg=f"missing the canonical diagnostic\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        self.assertNotIn(
            "Traceback (most recent call last)",
            combined,
            msg=f"an internal traceback is not a diagnostic\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )

    def test_operation_on_f8e3m4_is_refused(self) -> None:
        r = _run(OPERATION_PROBE, "gpu-part8-op")
        combined = r.stdout + r.stderr
        self.assertNotEqual(
            r.returncode, 0, msg=f"expected refusal\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
        self.assertIn(
            "operation with a type 'f8e3m4' is not implemented",
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
