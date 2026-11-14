#!/usr/bin/env python3
"""Pinning test for bug-hard-readme-4650: README index must reference only existing docs."""
import os, re
readme_path = "bugs/hard/README.md"

def test_readme_only_existing_docs():
    with open(readme_path) as f:
        content = f.read()
    names = re.findall(r'`([A-Z_]+\.md)`', content)
    for name in names:
        assert os.path.isfile(os.path.join("bugs/hard", name)), f"missing: {name}"

if __name__ == "__main__":
    test_readme_only_existing_docs()
    print("PASS: pinning test")
