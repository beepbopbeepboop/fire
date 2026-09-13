#!/usr/bin/env python3
"""No-shim self-hosted --dump-full artifact-content guard (DESIGN.html R6).

`MOJO_NO_SHIM=1 ./mojoc mojo.py --dump-full` exercises the self-hosted
compiler binary compiling itself, using its OWN compiled codegen instead of
the python3 shim every other check-* target drives through. A codegen bug
specific to that self-hosted path can silently produce a WRONG-BUT-SUCCESSFUL
mojo.ci (a whole sibling module gets dropped, an operator gets miscompiled,
...) with exit code 0 — no other gate step would ever see it, because they
all compile through the shim. This is not hypothetical: it is exactly what
happened on 2026-09-13 (see the mojo-reference2 project memory
"selfhost-dump-full-module-drop" / "design-container-typing-audit") — a fix
that made MOJO_NO_SHIM=1 ./mojoc ... --dump-full exit 0 instead of crashing
was actually WORSE than the crash it replaced, because the crash at least
happened after writing a byte-identical, correct .ci; the "fix" silently
dropped two sibling modules and exited clean.

So per DESIGN.html's R6: check the ARTIFACT (byte-identical to the shim's
own output), not just the exit code. `./mojoc` must already be built
(`make mojoc`) — this test does not build it, matching check-abshim's own
convention of depending on the `mojoc` Makefile target.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
MOJOC = os.path.join(REPO, "mojoc")
MOJO_MAIN = os.path.join(REPO, "mojo.py")


def _dump_full(env_extra: dict, use_mojoc: bool, cwd: str) -> tuple[int, bytes | None]:
    """Run --dump-full on mojo.py inside `cwd`, return (exit_code, .ci bytes
    or None if not produced)."""
    ci_path = os.path.join(cwd, "mojo.ci")
    if os.path.exists(ci_path):
        os.remove(ci_path)
    env = dict(os.environ)
    env.update(env_extra)
    if use_mojoc:
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

    shim_rc, shim_ci = _dump_full({}, use_mojoc=False, cwd=REPO)
    if shim_rc != 0 or not shim_ci:
        return False, f"shim (python3 mojo.py --dump-full) itself failed: exit {shim_rc}, {len(shim_ci or b'')} bytes"

    noshim_rc, noshim_ci = _dump_full(
        {"MOJO_NO_SHIM": "1", "MOJO_HOME": REPO}, use_mojoc=True, cwd=REPO)

    if noshim_ci is None:
        return False, (
            f"MOJO_NO_SHIM=1 ./mojoc mojo.py --dump-full produced NO mojo.ci "
            f"(exit {noshim_rc}) - the known original SIGBUS in "
            f"_rewrite_assign_stmt writes the correct file before crashing, "
            f"so an ABSENT file is a worse regression, not the known issue")

    if noshim_ci != shim_ci:
        # Report size + first differing byte offset - enough to triage
        # without dumping either 30MB+ artifact into test output.
        n = min(len(shim_ci), len(noshim_ci))
        first_diff = next((i for i in range(n) if shim_ci[i] != noshim_ci[i]), n)
        return False, (
            f"MOJO_NO_SHIM=1 ./mojoc output DIFFERS from the shim's own "
            f"--dump-full output: shim={len(shim_ci)} bytes, "
            f"no-shim={len(noshim_ci)} bytes, first differing byte at "
            f"offset {first_diff} - the self-hosted binary is miscompiling "
            f"itself even though it exited 0")

    if noshim_rc != 0:
        # Byte-identical output but a non-zero exit (the documented
        # crash-after-correct-write shape) - still a real regression for any
        # caller that checks exit status (e.g. a Makefile rule), but the
        # artifact itself is provably correct. Report distinctly from the
        # content-mismatch case above.
        return False, (
            f"MOJO_NO_SHIM=1 ./mojoc mojo.py --dump-full exited {noshim_rc} "
            f"(SIGBUS/crash) even though the written mojo.ci IS byte-"
            f"identical to the shim's - known issue, see "
            f"selfhost-dump-full-module-drop project memory")

    return True, f"byte-identical, {len(shim_ci)} bytes, both exit 0"


def main() -> int:
    try:
        ok, msg = run()
    except Exception as e:
        print("Results: 0 passed, 1 failed")
        print(f"✗ no-shim --dump-full check raised: {e}")
        return 1
    if ok:
        print("Results: 1 passed, 0 failed")
        print(f"✓ MOJO_NO_SHIM=1 ./mojoc mojo.py --dump-full matches shim ({msg})")
        return 0
    print("Results: 0 passed, 1 failed")
    print(f"✗ {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
