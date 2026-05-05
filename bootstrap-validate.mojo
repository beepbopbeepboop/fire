#!/usr/bin/env python3
"""
Bootstrap Validation - Compare pre-generated stage outputs for all *.mojo files
Verifies determinism by reading stage1.c, stage2.c, stage3.c and comparing bytes.
Assumes stages have been generated via: make stage1 stage2 stage3
"""

import os
import sys
from pathlib import Path

def validate_file(mojo_file):
    """
    Compare three-stage outputs for a single Mojo file.
    Returns True if all three stages have identical bytes.
    """
    base = mojo_file.replace(".mojo", "").replace("./", "").replace("/", "_")

    stage1_path = f"build/validate/{base}.stage1.c"
    stage2_path = f"build/validate/{base}.stage2.c"
    stage3_path = f"build/validate/{base}.stage3.c"

    # Check all files exist
    if not os.path.isfile(stage1_path):
        print(f"✗ {mojo_file} (missing stage1)")
        return False
    if not os.path.isfile(stage2_path):
        print(f"✗ {mojo_file} (missing stage2)")
        return False
    if not os.path.isfile(stage3_path):
        print(f"✗ {mojo_file} (missing stage3)")
        return False

    # Read and compare bytes
    try:
        with open(stage1_path, "rb") as f:
            stage1 = f.read()
        with open(stage2_path, "rb") as f:
            stage2 = f.read()
        with open(stage3_path, "rb") as f:
            stage3 = f.read()
    except Exception as e:
        print(f"✗ {mojo_file} (read error: {e})")
        return False

    # Compare
    if stage1 == stage2 and stage2 == stage3:
        print(f"✓ {mojo_file}")
        return True
    else:
        print(f"✗ {mojo_file}")
        return False

def main():
    """Find all *.mojo files and compare their stage outputs."""
    print("Bootstrap Validation - Comparing stage outputs for all .mojo files")
    print("═" * 80)
    print("")

    # Ensure output directory exists
    os.makedirs("build/validate", exist_ok=True)

    # Find all .mojo files (skip symlinks)
    mojo_files = []
    for root, dirs, files in os.walk("."):
        # Skip build directory
        if "build" in root:
            continue
        for file in sorted(files):
            if file.endswith(".mojo"):
                path = os.path.join(root, file)
                if not os.path.islink(path):
                    mojo_files.append(path)

    if not mojo_files:
        print("No .mojo files found")
        return

    # Validate each file (compare its stage outputs)
    passed = 0
    failed = 0

    for mojo_file in mojo_files:
        if validate_file(mojo_file):
            passed += 1
        else:
            failed += 1

    print("")
    print("═" * 80)
    print(f"Results: {passed} passed, {failed} failed")

    if failed > 0:
        sys.exit(1)

main()
