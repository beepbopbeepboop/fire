"""Part 5: an under-supplied specialization is a diagnostic, not a `None`.

Parent: `bugs/hard/GPU_offload_validation_modular.md` (row
`compile_offload_unbound_param_error.mojo`, interpreted half). This part's own
doc was deleted with the fix; it is pinned by this file.

Measured on the pre-fix tree (`fa105c747`): `fire.py run` on the first probe
exit 1 with a Python traceback --
`Error: unsupported operand type(s) for +: 'int' and 'NoneType'`, raised at
`myinterpreter.py`'s `_apply_binary_op` -- because `param_fn[2]` leaves the
declared comptime parameter `y` bound to `None`. The canonical Modular case
wants `failed to infer parameter 'y'` instead.

The second probe is the control: supplying both parameters already works
(prints `6`), so the fix must not turn every bracketed call into an error. The
third is the other control: a declared default (`y: Int = 4`) may be omitted,
which also covers the parser capturing the ANNOTATED default spelling rather
than swallowing `= 4` into the annotation.

Quick test: this file only (three interpreter runs, ~2 s, < 0.1 GB).
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from exec_budget import RUN_TIMEOUT


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

# Acceptance item 3: a comptime parameter with a declared DEFAULT may be
# omitted from the bracket (the under-supply refusal must not turn every
# short bracket into an error).
DEFAULTED = '''def param_fn[x: Int, y: Int = 4](a: Int) -> Int:
    return a + x + y


def main():
    print(param_fn[2](1))
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


class TestUnboundSpecializationParameter(unittest.TestCase):
    def test_under_supplied_bracket_is_a_diagnostic(self) -> None:
        r = _run(UNDER_SUPPLIED, "gpu-part5-unbound")
        combined = r.stdout + r.stderr
        self.assertNotEqual(
            r.returncode, 0, msg=f"expected refusal\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
        self.assertIn(
            "failed to infer parameter",
            combined,
            msg=f"missing the canonical diagnostic\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        self.assertIn(
            "'y'",
            combined,
            msg=f"diagnostic does not name the unbound parameter\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        self.assertIn(
            "param_fn",
            combined,
            msg=f"diagnostic does not name the callee\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        self.assertNotIn(
            "Traceback (most recent call last)",
            combined,
            msg=f"an internal traceback is not a diagnostic\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        self.assertNotIn(
            "'int' and 'NoneType'",
            combined,
            msg=f"the body still ran with the parameter unbound\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )

    def test_fully_supplied_bracket_still_runs(self) -> None:
        r = _run(FULLY_SUPPLIED, "gpu-part5-control")
        self.assertEqual(
            r.returncode, 0, msg=f"expected success\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
        self.assertIn("6", r.stdout)

    def test_defaulted_parameter_may_be_omitted(self) -> None:
        r = _run(DEFAULTED, "gpu-part5-default")
        self.assertEqual(
            r.returncode, 0, msg=f"expected success\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
        # x=2 from the bracket, y=4 from the declaration, a=1: 1 + 2 + 4.
        self.assertIn("7", r.stdout)


if __name__ == "__main__":
    unittest.main()
