#!/usr/bin/env python3
"""Check .mojo files against the parser and report pass/fail.

Usage:
  python3 tools/check_mojo_files.py                          # stdlib test + examples
  python3 tools/check_mojo_files.py path/to/dir [...]       # arbitrary directories
  python3 tools/check_mojo_files.py --base BASE path/to/dir # control rel-path display root
"""
import argparse, re, subprocess, sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
from module_loader import STDLIB_PATH
MOJO_ROOT = Path(STDLIB_PATH).parent.parent

DEFAULT_SOURCES = [
    MOJO_ROOT / "stdlib/test",
    MOJO_ROOT / "examples",
]


def check_file(path: Path, base: Path) -> tuple[bool, str]:
    """Return (passed, error_msg). error_msg is empty string on pass."""
    src = path.read_text()
    try:
        proc = subprocess.run(
            ["python3", "mojo_compiler.py"],
            input=src, capture_output=True, text=True, timeout=5, cwd=REPO
        )
        if proc.returncode != 0:
            lines = [l.strip() for l in proc.stderr.splitlines()
                     if l.strip() and not l.startswith(' ')]
            err = lines[-1][:120] if lines else "unknown error"
            return False, err
        if not proc.stdout.strip():
            stripped = re.sub(r'#[^\n]*', '', src).strip()
            if stripped:
                return False, "parser produced no output"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "timeout (>5s)"
    except Exception as e:
        return False, str(e)[:80]


def main():
    parser = argparse.ArgumentParser(description="Check .mojo files against the parser")
    parser.add_argument("dirs", nargs="*", help="Directories to scan (default: stdlib/test + examples)")
    parser.add_argument("--base", help="Root for relative path display")
    args = parser.parse_args()

    sources = [Path(d) for d in args.dirs] if args.dirs else DEFAULT_SOURCES
    display_base = Path(args.base) if args.base else MOJO_ROOT

    passed, failed = [], []

    for base in sources:
        for f in sorted(base.rglob("*.mojo")):
            rel = str(f.relative_to(display_base))
            ok, err = check_file(f, display_base)
            if ok:
                passed.append(rel)
            else:
                failed.append((rel, err))

    total = len(passed) + len(failed)
    pct = 100 * len(passed) / total if total else 0
    print(f"PASSED: {len(passed)}/{total}  ({pct:.1f}%)")
    print(f"FAILED: {len(failed)}/{total}")

    if failed:
        print()
        for rel, err in failed:
            print(f"FAIL  {rel}")
            print(f"      {err}")

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
