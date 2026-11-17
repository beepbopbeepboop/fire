"""Part 8 (fixed): refuse conversion/operation on an unsupported float8 dtype.

Host half of the `op_with_unsupported_type_error.mojo` row in
`bugs/hard/GPU_offload_validation_modular.md`: a scalar whose dtype has no
conversion or arithmetic rule here — the `float8` family the canonical case
uses (`float8_e3m4`) — must be refused at the point it is used, with the two
messages Modular prints: `conversion from 'f8e3m4' to 'f32' is not
implemented` and `operation with a type 'f8e3m4' is not implemented`. Before
the fix the float8 family did not exist in the interpreter's type table
(`DType.float8_e3m4` raised `AttributeError`), a `Float8_e3m4` annotation
was dropped, and `var b: Float32 = a` silently copied the value (`1.0`,
exit 0).

The same two refusals were owed by the COMPILED path, which accepted the
dtype silently: a bare
`fire.py <file>` used to exit 0 printing `1.0`/`3` because the annotation was
erased to an integer. The compiled half now resolves the dtype to its private
C type and refuses at the coercion and binary-operation chokepoints, so the
build stops with the same two messages.

Quick test: this file only (three interpreter runs, ~3 s, < 0.1 GB; three
compiled builds, ~2 min each on a cold compiler cache).
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from exec_budget import BUILD_TIMEOUT, RUN_TIMEOUT


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


def _build(src: str, stem: str) -> subprocess.CompletedProcess[str]:
    """Build `src` with `fire.py build`, the no-fallback compiled path.

    `fire.py <file>` interprets a program whose compile fails, so a diagnostic
    printed by the interpreter would make a refusal test pass without the
    compiled path ever refusing. `build` has no such fallback (the same reason
    part 6 builds rather than runs).
    """
    (ROOT / ".tmp").mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".mojo", delete=False, dir=ROOT / ".tmp"
    ) as f:
        f.write(src)
        path = Path(f.name)
    binary = ROOT / ".tmp" / stem
    binary.unlink(missing_ok=True)
    try:
        return subprocess.run(
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
    finally:
        path.unlink(missing_ok=True)


def _run_binary(binary: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=RUN_TIMEOUT
    )


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


class TestUnsupportedFloat8DtypeCompiled(unittest.TestCase):
    """The same two refusals on the COMPILED path (`fire.py build`).

    Before the compiled half of the fix, `var b: Float32 = a` was a plain
    float copy and `a + b` an ordinary float add: exit 0, `1.0`/`3`, no
    diagnostic, because the `Float8_e3m4` annotation was erased to an
    integer. `build` is used rather than the bare compile-and-run form so a
    failure cannot fall back to the interpreter (see `_build`).
    """

    def test_conversion_to_f32_is_refused_at_build(self) -> None:
        r = _build(CONVERSION_PROBE, "gpu-part8-compiled-convert")
        combined = r.stdout + r.stderr
        self.assertNotEqual(
            r.returncode, 0,
            msg=f"the compiled path accepted the conversion\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
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

    def test_operation_on_f8e3m4_is_refused_at_build(self) -> None:
        r = _build(OPERATION_PROBE, "gpu-part8-compiled-op")
        combined = r.stdout + r.stderr
        self.assertNotEqual(
            r.returncode, 0,
            msg=f"the compiled path accepted the operation\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
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

    def test_float8_declaration_holds_its_value(self) -> None:
        """A declaration that is never converted or operated on is allowed.

        The dtype's compiled representation is a `double` behind its private
        C typedef, so the value survives and prints as a float instead of
        falling through to the integer formatter.
        """
        src = '''def main():
    var a: Float8_e3m4 = 1.0
    print(a)
'''
        r = _build(src, "gpu-part8-compiled-decl")
        self.assertEqual(
            r.returncode, 0,
            msg=f"a bare float8 declaration stopped building\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )
        run = _run_binary(ROOT / ".tmp" / "gpu-part8-compiled-decl")
        self.assertEqual(
            run.returncode, 0,
            msg=f"the built binary failed\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}",
        )
        self.assertEqual(
            run.stdout.strip(), "1.0",
            msg=f"the float8 value did not survive its representation\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}",
        )

    def test_implemented_float_dtype_still_builds(self) -> None:
        """The guard must not reject an implemented float dtype."""
        src = '''def main():
    var a: Float32 = 1.5
    var b: Float32 = 2.5
    print(a + b)
'''
        r = _build(src, "gpu-part8-compiled-float32")
        self.assertEqual(
            r.returncode, 0,
            msg=f"an implemented dtype stopped building\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
