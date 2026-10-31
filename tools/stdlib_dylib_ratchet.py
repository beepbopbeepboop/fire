#!/usr/bin/env python3
"""Ratchet for the from-scratch stdlib dylib: fail only on a module that NEWLY falls back to source.

    python3 tools/stdlib_dylib_ratchet.py

`build_stdlib_dylib.build_stdlib()` builds the dylib and prints one `skip <module>: <why>` line per module that
could not be compiled (its clients fall back to source for it, so the failure is silent). The skip set must not
grow. The known set is `compile_stdlib.EXPECTED_FAILURES`, the same per-file baseline `stdlib-syntax` uses:
a module that is expected there is expected here, and a module that is not is a regression.

The symbol-collision exclusions (`excluded for symbol collisions`) are a separate, documented stopgap
(bug:CODEGEN_dylib_generic_inline_copies_share_one_symbol) and are reported, not gated.

Screen: only the verdict and any unexpected skip. The full build output goes to build/stdlib_dylib.log."""
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from compile_stdlib import EXPECTED_FAILURES  # noqa: E402  (the one baseline, shared with stdlib-syntax)
from module_loader import STDLIB_PATH  # noqa: E402

LOG = os.path.join(ROOT, "build", "stdlib_dylib.log")


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    r = subprocess.run([sys.executable, "-c", "import build_stdlib_dylib as b; b.build_stdlib()"],
                       cwd=ROOT, capture_output=True, text=True)
    out = r.stdout + r.stderr
    open(LOG, "w").write(out)
    if r.returncode != 0:
        print("stdlib-dylib: the build itself FAILED (exit %d); full output in %s" % (r.returncode, LOG))
        return 1
    skipped = []
    for line in out.splitlines():
        m = re.match(r"\s*skip (\S+?): ", line)
        if m:
            rel = m.group(1).split("stdlib/", 1)[-1]
            skipped.append((rel, line.strip()))
    unexpected = [(rel, why) for rel, why in skipped if rel not in EXPECTED_FAILURES]
    stale = sorted(set(EXPECTED_FAILURES) - {rel for rel, _ in skipped} - _not_in_sweep())
    excluded = re.search(r"\((\d+) modules excluded", out)
    print("stdlib-dylib: %d module(s) fell back to source (%d expected), %d symbol-collision exclusion(s) reported"
          % (len(skipped), len(skipped) - len(unexpected), int(excluded.group(1)) if excluded else 0))
    if unexpected:
        print("NEW dylib skips (not in compile_stdlib.EXPECTED_FAILURES):")
        for rel, why in unexpected:
            print("  " + why[:200])
        return 1
    if stale:
        print("note: expected modules that now build into the dylib (remove from EXPECTED_FAILURES): "
              + ", ".join(stale))
    return 0


def _not_in_sweep():
    # An entry with no source file is GONE, not stale; compile_stdlib reports it itself.
    return {rel for rel in EXPECTED_FAILURES if not os.path.exists(os.path.join(STDLIB_PATH, rel))}


if __name__ == "__main__":
    sys.exit(main())
