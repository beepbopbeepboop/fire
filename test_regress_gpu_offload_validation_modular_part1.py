"""Pins the GPU offload validation triage (part 1).

Part 1 was a documentation-only triage of the 10 Modular cases in
`bugs/hard/GPU_offload_validation_modular.md`.  Its doc was deleted when the
matrix was folded into that parent (`## Triage (part 1)`), which is now where
parts 2 and 3 are told to look.  This test keeps the matrix from rotting and
pins the two classifications that are checkable from the tree:

- the `max.gpu`-import cases (bundle order, both enqueue/device-passable
  closures, the end-to-end thunk) are blocked on module names this tree does
  not resolve: the interpreter auto-stubs `std.*` but a program importing
  `max.gpu.host` still fails with `No module named 'max'`;
- `simd_bad_size_lowering` is only partly addressed: part 4's interpreter
  guard rejects widths 0/-1/3, while the compiled path is still unguarded
  (tracked by `bugs/CODEGEN_simd_width_guard_compiled_path.md`).

If the parent doc is deleted because parts 2/3 have landed, this test should be
deleted with it: what it pins is the triage record, not a compiler behaviour
that outlives the record.

Quick test: this file only.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PARENT = ROOT / "bugs" / "hard" / "GPU_offload_validation_modular.md"

CASES = [
    "compile_offload_unbound_param_error.mojo",
    "compile_offload_missing_symbol_error.mojo",
    "compile_offload_bundle_order.mojo",
    "enqueue_function_device_passable_closure_arg_error.mojo",
    "enqueue_function_device_passable_closure_arg_layout_error.mojo",
    "sanitize_address.mojo",
    "sanitize_address_inlined.mojo",
    "op_with_unsupported_type_error.mojo",
    "end_to_end_thunk_with_direct_compile.mojo",
    "simd_bad_size_lowering.mojo",
]

FOLLOW_UPS = ("part2", "part3", "part4", "out-of-scope")


def _triage_section() -> list[str]:
    lines = PARENT.read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("## Triage (part 1")),
        None,
    )
    if start is None:
        return []
    section = []
    for line in lines[start:]:
        if section and line.startswith("## "):
            break
        section.append(line)
    return section


class TestGpuOffloadValidationPart1(unittest.TestCase):
    def test_parent_doc_holds_one_triage_row_per_case(self):
        section = _triage_section()
        self.assertTrue(
            section,
            msg=f"{PARENT} has no '## Triage (part 1' section; the part-1 "
            "matrix is where parts 2 and 3 are told to look",
        )
        rows = [line for line in section if line.startswith("| `")]
        self.assertEqual(
            len(rows), len(CASES), msg=f"expected {len(CASES)} triage rows, got {len(rows)}"
        )
        for case in CASES:
            with self.subTest(case=case):
                matches = [row for row in rows if f"`{case}`" in row]
                self.assertEqual(
                    len(matches), 1, msg=f"expected exactly one triage row for {case}"
                )
                self.assertTrue(
                    any(follow in matches[0] for follow in FOLLOW_UPS),
                    msg=f"{case} row has no part2/part3/part4/out-of-scope follow-up: {matches[0]}",
                )

    def test_max_gpu_import_is_still_unresolvable(self):
        (ROOT / ".tmp").mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".mojo", delete=False, dir=ROOT / ".tmp"
        ) as f:
            f.write(
                "from max.gpu.host import DeviceContext\n"
                "\n"
                "\n"
                "def main():\n"
                "    pass\n"
            )
            path = Path(f.name)
        try:
            r = subprocess.run(
                [
                    sys.executable,
                    "tools/memslot.py",
                    "--gb",
                    "8",
                    "--label",
                    "gpu-part1-max",
                    "--",
                    sys.executable,
                    "fire.py",
                    "run",
                    str(path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            path.unlink(missing_ok=True)
        combined = r.stdout + r.stderr
        self.assertNotEqual(
            r.returncode,
            0,
            msg=f"expected max.gpu.host to remain unresolved\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        self.assertIn(
            "No module named 'max'",
            combined,
            msg=f"expected ModuleNotFoundError for 'max'\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )

    def test_interpreter_simd_width_guard_is_intact(self):
        import myinterpreter

        valid = (1, 2, 4, 32768)
        invalid = (0, -1, 3, 5, 32769, 65536)
        for width in valid:
            with self.subTest(width=width):
                self.assertTrue(myinterpreter._mojo_simd_width_is_valid(width))
        for width in invalid:
            with self.subTest(width=width):
                self.assertFalse(myinterpreter._mojo_simd_width_is_valid(width))


if __name__ == "__main__":
    unittest.main()
