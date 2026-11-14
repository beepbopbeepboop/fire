"""Focused regressions for GPU offload validation modular part 4 dispositions.

Part 4 dispositions:
- simd_bad_size_lowering.mojo: compiler-side SIMD width validation is feasible
  without a GPU backend. This test pins interpreter (`fire.py run`) and
  compiled (`fire.py <file>`) rejection of invalid literal SIMD widths
  (0, -1, 3), including the lowered `!kgen.simd<N, dtype>` spelling in the
  compiled diagnostic.
- op_with_unsupported_type_error.mojo: lowering/target-specific type legality
  (e.g. float8_e3m4 ops, NVPTX emission via kgen) is documented as blocked in
  the bug doc; no GPU/type-lowering backend support claimed here.
- sanitize_address*.mojo, end_to_end_thunk_with_direct_compile.mojo: depend on
  sanitizer/GPU backend/runtime/thunk capabilities and are documented as
  blocked in the bug doc with prerequisite checklists.

Quick test: this file only.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MEMSLOT = [sys.executable, "tools/memslot.py", "--gb", "8", "--label", "gpu-part4"]


def _run_mojo(src: str, label: str, mode: str = "run") -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".mojo", delete=False, dir=ROOT / ".tmp") as f:
        f.write(src)
        path = Path(f.name)
    try:
        return subprocess.run(
            [sys.executable, "tools/memslot.py", "--gb", "8", "--label", label,
             "--", sys.executable, "fire.py"]
            + ([mode] if mode else [])
            + [str(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
    finally:
        path.unlink(missing_ok=True)
        # Bare `fire.py <file>` links its executable beside the CWD (named
        # after the source stem), which is the repo root here. Remove it so
        # running this test does not leave an untracked binary behind.
        (ROOT / path.stem).unlink(missing_ok=True)


class TestGpuOffloadValidationPart4(unittest.TestCase):
    def test_simd_bad_size_literal_widths_rejected(self):
        cases = [
            ("zero", "SIMD[DType.float32, 0](0.0)", "0"),
            ("neg", "SIMD[DType.float32, -1](0.0)", "-1"),
            ("non_pow2", "SIMD[DType.float32, 3](0.0)", "3"),
        ]
        for label, expr, needle in cases:
            with self.subTest(label=label):
                src = f"def main():\n    var x = {expr}\n    print(x)\n"
                r = _run_mojo(src, f"simd-{label}")
                self.assertNotEqual(
                    r.returncode, 0,
                    msg=f"expected failure for {expr}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
                )
                combined = r.stdout + r.stderr
                self.assertIn(
                    "SIMD vector length must be a power of two",
                    combined,
                    msg=f"missing SIMD width diagnostic for {expr}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
                )
                self.assertIn(
                    needle, combined,
                    msg=f"missing offending width for {expr}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
                )

    def test_simd_valid_power_of_two_width_still_runs(self):
        src = "def main():\n    var x = SIMD[DType.float32, 4](1.0)\n    print(len(x))\n"
        r = _run_mojo(src, "simd-ok")
        self.assertEqual(
            r.returncode, 0,
            msg=f"expected success\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        self.assertIn("4", r.stdout)

    def test_simd_bad_size_compiled_path_rejects_before_lowering(self):
        """`python3 fire.py <file>` (compile and run) must reject a bad width.

        Part 4 only guarded `fire.py run`, so this spelling printed `1.0` and
        exited 0. The compiled path raises the diagnostic at the point it
        builds the `SIMD[dtype, width]` type, naming the LOWERED type the
        canonical `simd_bad_size_lowering.mojo` FileCheck matches.
        """
        cases = [
            ("zero", "SIMD[DType.float32, 0](0.0)", "!kgen.simd<0, f32>"),
            ("neg", "SIMD[DType.float32, -1](0.0)", "!kgen.simd<-1, f32>"),
            ("non_pow2", "SIMD[DType.float32, 3](1.0)", "!kgen.simd<3, f32>"),
        ]
        for label, expr, lowered in cases:
            with self.subTest(label=label):
                src = f"def main():\n    var x = {expr}\n    print(x)\n"
                r = _run_mojo(src, f"simd-compiled-{label}", mode="")
                self.assertNotEqual(
                    r.returncode, 0,
                    msg=f"expected failure for {expr}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
                )
                combined = r.stdout + r.stderr
                self.assertIn(
                    "SIMD vector length must be a power of two",
                    combined,
                    msg=f"missing SIMD width diagnostic for {expr}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
                )
                self.assertIn(
                    lowered,
                    combined,
                    msg=f"diagnostic did not name the lowered type for {expr}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
                )

    def test_simd_valid_width_still_compiles_and_runs(self):
        src = "def main():\n    var x = SIMD[DType.float32, 4](1.0)\n    print(x)\n"
        r = _run_mojo(src, "simd-compiled-ok", mode="")
        self.assertEqual(
            r.returncode, 0,
            msg=f"expected success\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        self.assertIn("1.0", r.stdout)


if __name__ == "__main__":
    unittest.main()
