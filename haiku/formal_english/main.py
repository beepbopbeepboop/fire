#!/usr/bin/env python3
"""
Formal English Transpiler CLI.

Usage:
    python -m formal_english.main input.fe [output.py]
    python -m formal_english.main input.fe --stdout
    python -m formal_english.main --help
"""
import sys
import argparse
from pathlib import Path
from . import transpile
from .errors import FormalEnglishError


def main():
    parser = argparse.ArgumentParser(
        prog="formal_english",
        description="Transpile Formal English to Python"
    )
    parser.add_argument("input", help="Input .fe file path")
    parser.add_argument("output", nargs="?", help="Output .py file path (default: same name with .py extension)")
    parser.add_argument("--stdout", action="store_true", help="Write output to stdout instead of a file")
    parser.add_argument("--check", action="store_true", help="Parse and check without emitting output")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    source = input_path.read_text(encoding="utf-8")

    try:
        python_source = transpile(source)
    except FormalEnglishError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.check:
        print("OK")
        return

    if args.stdout:
        print(python_source)
        return

    output_path = Path(args.output) if args.output else input_path.with_suffix(".py")
    output_path.write_text(python_source, encoding="utf-8")
    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()
