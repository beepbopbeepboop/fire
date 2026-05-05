#!/usr/bin/env python3
"""
Bootstrap Validation - Verify deterministic compilation across three stages
Compares stage1/mojo.ci, stage2/mojo.ci, stage3/mojo.ci for byte identity.
"""

import os
import sys

def main():
    """Verify three-stage bootstrap outputs are identical."""
    print("Bootstrap Validation - Verifying stage outputs")
    print("═" * 80)
    print("")

    stage1_path = "stage1/mojo.ci"
    stage2_path = "stage2/mojo.ci"
    stage3_path = "stage3/mojo.ci"

    # Check all files exist
    if not os.path.isfile(stage1_path):
        print(f"✗ stage1/mojo.ci missing")
        sys.exit(1)
    if not os.path.isfile(stage2_path):
        print(f"✗ stage2/mojo.ci missing")
        sys.exit(1)
    if not os.path.isfile(stage3_path):
        print(f"✗ stage3/mojo.ci missing")
        sys.exit(1)

    # Read and compare bytes
    try:
        with open(stage1_path, "rb") as f:
            stage1 = f.read()
        with open(stage2_path, "rb") as f:
            stage2 = f.read()
        with open(stage3_path, "rb") as f:
            stage3 = f.read()
    except Exception as e:
        print(f"✗ Error reading files: {e}")
        sys.exit(1)

    # Compare
    print(f"stage1/mojo.ci: {len(stage1)} bytes")
    print(f"stage2/mojo.ci: {len(stage2)} bytes")
    print(f"stage3/mojo.ci: {len(stage3)} bytes")
    print("")

    if stage1 == stage2 and stage2 == stage3:
        print("✓ All three stages produce identical GIMPLE code")
        print("═" * 80)
        print("")
        sys.exit(0)
    else:
        print("✗ Stages differ - bootstrap is not deterministic")
        if stage1 != stage2:
            print("  stage1 ≠ stage2")
        if stage2 != stage3:
            print("  stage2 ≠ stage3")
        print("═" * 80)
        print("")
        sys.exit(1)

main()
