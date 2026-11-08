"""Regression: Python 3.15 profiling package submodules resolve in the interpreter.

CPython 3.15 adds the `profiling` package (sampling/tracing). `from profiling
import tracing` must bind the real submodule even though the package does not
expose it as an attribute until imported (PEP 451 / package submodule
semantics). The interpreter previously fell back to an auto-stub here.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _run_fire(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", dir=HERE, delete=False) as f:
        f.write(src)
        path = f.name
    try:
        return subprocess.run(
            [sys.executable, os.path.join(HERE, "fire.py"), "run", path],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_profiling_package_submodule_imports():
    # Requires Python 3.15+ host with the profiling package.
    probe = subprocess.run(
        [sys.executable, "-c", "import profiling; from profiling import tracing, sampling"],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        # Host lacks the 3.15 profiling package; nothing to assert for fire.
        return

    src = """\
import profiling
assert 'tracing' in getattr(profiling, '__all__', ())
assert 'sampling' in getattr(profiling, '__all__', ())
# Submodules are not package attributes until imported.
try:
    _ = profiling.tracing
    raised = False
except AttributeError:
    raised = True
assert raised, 'profiling.tracing should not be an attribute before import'
from profiling import tracing, sampling
assert hasattr(profiling, 'tracing')
assert hasattr(profiling, 'sampling')
assert tracing.__name__ == 'profiling.tracing'
assert sampling.__name__ == 'profiling.sampling'
# Dotted submodule imports also work.
from profiling.tracing import TracebackLimit
from profiling.sampling import Collector
print('ok')
"""
    r = _run_fire(src)
    assert r.returncode == 0, f"fire run failed:\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    assert "ok" in r.stdout, f"unexpected output:\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
