#!/usr/bin/env python3
"""
Test transpiling markdown files as Formal English.
"""
import sys
from pathlib import Path
from formal_english import transpile
from formal_english.errors import FormalEnglishError


def test_transpile_markdown(md_file, use_preprocessor: bool = True):
    """Try to transpile a markdown file."""
    try:
        with open(md_file, 'r') as f:
            content = f.read()

        # Try to transpile with markdown preprocessing
        python_code = transpile(content, preprocess_markdown=use_preprocessor)
        return True, None, python_code
    except FormalEnglishError as e:
        return False, str(e), None
    except Exception as e:
        return False, str(e), None


def main():
    # Get all mojo-*.md files except EXAMPLES.md
    md_files = sorted([f for f in Path('.').glob('mojo-*.md') if f.name != 'EXAMPLES.md'])

    if not md_files:
        print("No markdown files found")
        return 1

    print("=" * 80)
    print("Testing Markdown Transpilation (With Preprocessor)")
    print("=" * 80)

    results = {}

    for md_file in md_files:
        print(f"\n{md_file.name}:")

        # Test with preprocessing enabled
        success, error, python_code = test_transpile_markdown(md_file, use_preprocessor=True)

        if success:
            print(f"  ✓ Transpilation successful (with preprocessing)")
            print(f"  Generated {len(python_code)} bytes of Python code")
            lines_of_code = len([l for l in python_code.split('\n') if l.strip()])
            print(f"  Lines of code: {lines_of_code}")
            results[md_file.name] = ("PASS", None)
        else:
            print(f"  ✗ Transpilation failed (with preprocessing)")
            if error and len(error) < 150:
                print(f"  Error: {error}")
            results[md_file.name] = ("FAIL", error)

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    passed = sum(1 for status, _ in results.values() if status == "PASS")
    failed = sum(1 for status, _ in results.values() if status == "FAIL")
    total = len(results)

    for filename, (status, error) in results.items():
        symbol = "✓" if status == "PASS" else "✗"
        print(f"{symbol} {filename}: {status}")
        if error and len(error) < 100:
            print(f"    {error}")

    print(f"\nTotal: {total} files")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success Rate: {100 * passed / total:.1f}%")
    print("=" * 80)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
