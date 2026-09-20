#!/usr/bin/env python3
"""Self-hosted --dump-full artifact-content guard (DESIGN.html R6).

`./mojoc fire.py --dump-full` exercises the self-hosted compiler binary
compiling itself, using its OWN compiled (native) codegen instead of the
python3-interpreted reference every other check-* target drives through. A
codegen bug specific to that native path can silently produce a
WRONG-BUT-SUCCESSFUL fire.ci (a whole sibling module gets dropped, an
operator gets miscompiled, ...) with exit code 0 — no other gate step would
ever see it, because they all compile through the python3 reference
interpreter. This is not hypothetical: it is exactly what happened on
2026-09-13 (see the mojo-reference2 project memory
"selfhost-dump-full-module-drop" / "design-container-typing-audit") — a fix
that made `./mojoc ... --dump-full` exit 0 instead of crashing was actually
WORSE than the crash it replaced, because the crash at least happened after
writing a byte-identical, correct .ci; the "fix" silently dropped two
sibling modules and exited clean.

So per DESIGN.html's R6: check the ARTIFACT (byte-identical to the python3
reference's own output), not just the exit code. `./mojoc` must already be
built (`make mojoc`) — this test does not build it, matching
check-ab-native's own convention of depending on the `mojoc` Makefile
target.

(Formerly test_noshim_dumpfull.py / "shim vs no-shim": the self-hosted
binary's `gimple_codegen_compile_to_gimple` C runtime wrapper used to fall
back to spawning a python3 subprocess unless `MOJO_NO_SHIM=1` was set. That
subprocess fallback is gone — the wrapper always calls the compiled native
`compile_to_gimple` directly now — so there is no longer an env var to set;
this test simply compares the python3-interpreted reference against the
self-hosted binary's own native compile.)
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
MOJOC = os.path.join(REPO, "mojoc")
MOJO_MAIN = os.path.join(REPO, "fire.py")


def _dump_full(use_mojoc: bool, cwd: str) -> tuple[int, bytes | None]:
    """Run --dump-full on fire.py inside `cwd`, return (exit_code, .ci bytes
    or None if not produced)."""
    ci_path = os.path.join(cwd, "fire.ci")
    if os.path.exists(ci_path):
        os.remove(ci_path)
    env = dict(os.environ)
    if use_mojoc:
        env["MOJO_HOME"] = REPO
        cmd = [MOJOC, MOJO_MAIN, "--dump-full"]
    else:
        cmd = [sys.executable, MOJO_MAIN, "--dump-full", MOJO_MAIN]
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True)
    data = None
    if os.path.exists(ci_path):
        with open(ci_path, "rb") as f:
            data = f.read()
        os.remove(ci_path)
    return proc.returncode, data


def run() -> tuple[bool, str]:
    if not os.path.exists(MOJOC):
        return False, f"{MOJOC} not built - run `make mojoc` first"

    python_rc, python_ci = _dump_full(use_mojoc=False, cwd=REPO)
    if python_rc != 0 or not python_ci:
        return False, f"python3 fire.py --dump-full itself failed: exit {python_rc}, {len(python_ci or b'')} bytes"

    native_rc, native_ci = _dump_full(use_mojoc=True, cwd=REPO)

    if native_ci is None:
        return False, (
            f"./mojoc fire.py --dump-full produced NO fire.ci "
            f"(exit {native_rc}) - the known original SIGBUS in "
            f"_rewrite_assign_stmt writes the correct file before crashing, "
            f"so an ABSENT file is a worse regression, not the known issue")

    if native_ci != python_ci:
        # Report size + first differing byte offset - enough to triage
        # without dumping either 30MB+ artifact into test output.
        n = min(len(python_ci), len(native_ci))
        first_diff = next((i for i in range(n) if python_ci[i] != native_ci[i]), n)
        return False, (
            f"./mojoc output DIFFERS from the python3 reference's own "
            f"--dump-full output: python={len(python_ci)} bytes, "
            f"native={len(native_ci)} bytes, first differing byte at "
            f"offset {first_diff} - the self-hosted binary is miscompiling "
            f"itself even though it exited 0")

    if native_rc != 0:
        # Byte-identical output but a non-zero exit (the documented
        # crash-after-correct-write shape) - still a real regression for any
        # caller that checks exit status (e.g. a Makefile rule), but the
        # artifact itself is provably correct. Report distinctly from the
        # content-mismatch case above.
        return False, (
            f"./mojoc fire.py --dump-full exited {native_rc} "
            f"(SIGBUS/crash) even though the written fire.ci IS byte-"
            f"identical to the python3 reference's - known issue, see "
            f"selfhost-dump-full-module-drop project memory")

    return True, f"byte-identical, {len(python_ci)} bytes, both exit 0"


def main() -> int:
    try:
        ok, msg = run()
    except Exception as e:
        print("Results: 0 passed, 1 failed")
        print(f"✗ native --dump-full check raised: {e}")
        return 1
    if ok:
        print("Results: 1 passed, 0 failed")
        print(f"✓ ./mojoc fire.py --dump-full matches python3 reference ({msg})")
        return 0
    print("Results: 0 passed, 1 failed")
    print(f"✗ {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
