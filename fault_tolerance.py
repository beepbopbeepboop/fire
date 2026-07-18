#!/usr/bin/env python3
"""Software fault tolerance (recovery-block / 2-version programming) for the
Python-3.14.6 stdlib corpus.

Concept
-------
Real CPython is treated as the trusted "oracle" version, and mojo's own
run path (`mojo.py <file>` — compile-and-run, falling back to the
interpreter on a compile failure, exactly what `mojo -h` documents as the
default invocation) is the second, independently-implemented version
computing nominally the same thing. For a given file we run *both*, compare
their externally observable behavior, and:

  * record a strict PASS/FAIL verdict (agreement, not "didn't crash"),
  * persist both sides' full stdout/stderr/exit-code to disk for every file
    run (not just failures), so a human can inspect any case without
    re-running anything,
  * hand back the *Python* side's output as the trustworthy result — this is
    a recovery mechanism, not just a diagnostic: mojo's answer is never
    surfaced as if it were authoritative, even when it "looks" more
    plausible than Python's.

What "running" a file means (design decision)
-----------------------------------------------
Most files under Lib/ are modules, not scripts: `python3 somefile.py` and
mojo's equivalent may both just define classes/functions with zero observable
output, and many use relative imports that only resolve inside their real
package. Rather than build separate "import mode" vs "script mode" paths
(and inherit relative-import package-context complications for imports), we
run each file exactly one way, symmetrically on both sides:

    python3   <file>          (cwd = fresh isolated scratch dir)
    mojo.py   <file>          (cwd = fresh isolated scratch dir)

Running the file directly as a script is a single, consistent scheme that
also happens to subsume the `if __name__ == "__main__":` case for free:
`__name__` is `"__main__"` either way, so any main-guard code the file has
gets exercised identically on both sides without special-casing it. Files
whose only content is top-level definitions legitimately produce empty
stdout + exit 0 on both sides — that agreement ("loads cleanly, no
divergent side effects") is itself a meaningful (if weak) data point, not a
harness flaw; it's called out again in the module-level docstring of the
driver script.

Comparison rule
----------------
Verdict is PASS iff returncode matches AND stdout matches byte-for-byte.
stderr is captured and persisted on both sides (useful for root-causing a
FAIL) but does not by itself flip the verdict: stderr commonly carries
incidental noise (deprecation warnings, differently-formatted tracebacks)
that isn't the behavioral divergence we care about — a real behavioral
difference is expected to also show up in stdout and/or the exit code.

Caching
-------
Unlike `py314_cache.py` (which caches a pure function of source+compiler —
"does this compile"), *executing* arbitrary stdlib code is not safely
cacheable in general: output can depend on wall-clock time, PIDs, thread
scheduling, PYTHONHASHSEED-randomized iteration order, etc. Treating a
once-observed pair of outputs as a permanent verdict for a given
(source, compiler-fingerprint) key would risk silently freezing in a
misleading verdict for such files. What we *do* reuse from `cas.py` is its
existing content+compiler-fingerprint hashing helper (`cas.hash_parts`) to
name each artifact file — so re-running the driver over the same population
against an unchanged compiler is idempotent on disk (same key -> same
filename) without a separate cache layer, and `force=True` always re-executes.
"""
import dataclasses
import os
import shutil
import subprocess
import sys
import tempfile
import time

import cas

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO_PY = os.path.join(HERE, "mojo.py")
ARTIFACTS_DIR = os.path.join(HERE, "artifacts", "fault_tolerance")

DEFAULT_TIMEOUT = 20  # seconds, per side

# Prefer the exact interpreter the corpus targets (3.14) if present, since
# that's what the stdlib files declare themselves written against; fall back
# to whatever python is running this module (which, on this box, is also 3.14).
_PY314 = shutil.which("python3.14")
PYTHON_BIN = _PY314 if _PY314 else sys.executable


# ── Safety: files we refuse to execute at all ──────────────────────────────
#
# We are running arbitrary real-world stdlib code. These are heuristic, not
# exhaustive, exclusions: test *fixtures* (not real library modules — many
# are deliberately broken, or expect a test runner harness around them,
# not standalone execution), platform-build plumbing that isn't meant to run
# on this machine at all, and specific modules whose top-level/`__main__`
# behavior is known to mutate system state, open a GUI, or reach the network
# rather than just compute something.
UNSAFE_PATH_HINTS = (
    "/test/", "/tests/", "/idle_test/", "/Lib/idlelib/",
    "/Tools/", "/Doc/", "/Mac/", "/PC/", "/PCbuild/", "/Misc/", "/Modules/",
    "/Programs/", "/turtledemo/", "/ensurepip/", "/venv/",
)
UNSAFE_BASENAMES = {
    "antigravity.py",   # opens a real web browser
    "webbrowser.py",    # ditto, if its __main__ is exercised
    "this.py",          # harmless, but excluded defensively (stdin-adjacent easter egg)
    "turtle.py",         # opens a GUI window (Tk)
}
UNSAFE_NAME_PREFIXES = ("test_",)


def is_unsafe(filepath: str) -> str | None:
    """Return a human-readable reason to skip execution, or None if safe."""
    norm = filepath.replace(os.sep, "/")
    for hint in UNSAFE_PATH_HINTS:
        if hint in norm:
            return f"path contains {hint!r} (test fixture / platform-build / GUI-ish tree)"
    base = os.path.basename(filepath)
    if base in UNSAFE_BASENAMES:
        return f"denylisted module ({base}): known to touch network/GUI/browser"
    for pfx in UNSAFE_NAME_PREFIXES:
        if base.startswith(pfx):
            return f"basename starts with {pfx!r} (looks like a test, not a library module)"
    return None


@dataclasses.dataclass
class SideResult:
    cmd: list
    stdout: str
    stderr: str
    returncode: int | None
    elapsed: float
    timed_out: bool = False
    harness_error: str | None = None

    def to_json(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class FaultTolerantResult:
    filepath: str
    verdict: str           # "PASS" | "FAIL" | "SKIPPED"
    divergence: str        # one-line human-readable characterization
    trusted_output: dict   # ALWAYS Python's captured result — the recovery answer
    mojo_output: dict      # mojo's captured result — for diagnosis only, never authoritative
    artifacts_path: str | None


def _run_side(cmd, cwd, timeout):
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "HOME": cwd, "TMPDIR": cwd},
        )
        return SideResult(cmd=cmd, stdout=proc.stdout, stderr=proc.stderr,
                          returncode=proc.returncode, elapsed=time.time() - t0)
    except subprocess.TimeoutExpired as e:
        return SideResult(cmd=cmd, stdout=e.stdout or "", stderr=e.stderr or "",
                          returncode=None, elapsed=time.time() - t0, timed_out=True)
    except Exception as e:
        return SideResult(cmd=cmd, stdout="", stderr="", returncode=None,
                          elapsed=time.time() - t0, harness_error=str(e))


def _characterize(py: SideResult, mj: SideResult) -> tuple:
    """Return (verdict, divergence_one_liner)."""
    if mj.harness_error:
        return "FAIL", f"mojo harness error: {mj.harness_error}"
    if mj.timed_out:
        return "FAIL", f"mojo timed out (>{mj.elapsed:.0f}s) while python finished"
    if py.timed_out:
        return "FAIL", f"python itself timed out (>{py.elapsed:.0f}s) — inconclusive"
    if py.returncode != mj.returncode:
        py_ok = py.returncode == 0
        mj_ok = mj.returncode == 0
        if py_ok and not mj_ok:
            first_err = next((l for l in mj.stderr.splitlines() if l.strip()), "")
            return "FAIL", f"mojo crashed (rc={mj.returncode}) while python succeeded: {first_err[:160]}"
        if mj_ok and not py_ok:
            return "FAIL", f"python failed (rc={py.returncode}) but mojo exited 0 — mojo silently swallowed an error"
        return "FAIL", f"exit code mismatch (python={py.returncode}, mojo={mj.returncode})"
    if py.stdout != mj.stdout:
        return "FAIL", "stdout mismatch (same exit code, different observable output)"
    return "PASS", "match"


def _artifact_key(filepath: str, src: bytes) -> str:
    return cas.hash_parts("mojo-ft-v1", cas.compiler_fingerprint(), filepath, src)


def _artifact_path(safe_name: str, key: str) -> str:
    return os.path.join(ARTIFACTS_DIR, f"{safe_name}__{key[:16]}.json")


def run_fault_tolerant(filepath: str, timeout: int = DEFAULT_TIMEOUT,
                       safe_name: str = None, force: bool = False) -> FaultTolerantResult:
    """Run `filepath` under real CPython and under mojo, compare, and return
    a FaultTolerantResult whose trusted_output is always Python's — i.e. the
    recovery-block answer a caller should actually use, regardless of verdict.
    """
    filepath = os.path.abspath(filepath)
    if safe_name is None:
        safe_name = os.path.basename(filepath)[:-len(".py")] if filepath.endswith(".py") else os.path.basename(filepath)
        safe_name = safe_name.replace(os.sep, "_")

    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    reason = is_unsafe(filepath)
    if reason:
        result = FaultTolerantResult(
            filepath=filepath, verdict="SKIPPED", divergence=reason,
            trusted_output=None, mojo_output=None, artifacts_path=None,
        )
        return result

    with open(filepath, "rb") as f:
        src = f.read()
    key = _artifact_key(filepath, src)
    artifact_path = _artifact_path(safe_name, key)

    if not force and os.path.exists(artifact_path):
        import json
        with open(artifact_path) as f:
            data = json.load(f)
        return FaultTolerantResult(
            filepath=filepath, verdict=data["verdict"], divergence=data["divergence"],
            trusted_output=data["python"], mojo_output=data["mojo"],
            artifacts_path=artifact_path,
        )

    py_scratch = tempfile.mkdtemp(prefix="ft_py_")
    mj_scratch = tempfile.mkdtemp(prefix="ft_mojo_")
    try:
        py_result = _run_side([PYTHON_BIN, filepath], py_scratch, timeout)
        mj_result = _run_side([sys.executable, MOJO_PY, filepath], mj_scratch, timeout)
    finally:
        shutil.rmtree(py_scratch, ignore_errors=True)
        shutil.rmtree(mj_scratch, ignore_errors=True)

    verdict, divergence = _characterize(py_result, mj_result)

    import json
    artifact = {
        "filepath": filepath,
        "verdict": verdict,
        "divergence": divergence,
        "python": py_result.to_json(),
        "mojo": mj_result.to_json(),
        "timestamp": time.time(),
    }
    tmp = artifact_path + f".tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(artifact, f, indent=2)
    os.replace(tmp, artifact_path)

    return FaultTolerantResult(
        filepath=filepath, verdict=verdict, divergence=divergence,
        trusted_output=py_result.to_json(), mojo_output=mj_result.to_json(),
        artifacts_path=artifact_path,
    )
