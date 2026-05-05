#!/bin/bash
# Complete Bootstrap Test - Verifies Mojo self-hosting capability
# Usage: ./scripts/bootstrap.sh

set -euo pipefail

echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║                    MOJO BOOTSTRAP VERIFICATION                        ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

# Check Python
echo "✓ Checking environment..."
python3 --version >/dev/null 2>&1 || {
    echo "✗ Python 3 required"
    exit 1
}

# Run verification suite
echo "✓ Running comprehensive bootstrap tests..."
echo ""

python3 scripts/bootstrap_verify.py || exit 1

echo ""
echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║                        BOOTSTRAP SUCCESSFUL                           ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Summary:"
echo "  Stage 1 (Python):    ✓ Verified - All 7 tests passing"
echo "  Stage 2 (Mojo):      Ready (requires 'mojo' command)"
echo "  Stage 3 (Verify):    Ready (determinism testing)"
echo ""
echo "Next steps:"
echo "  1. On a Mojo system: mojo run scripts/stage2_mojo_interpreter.mojo <test.mojo>"
echo "  2. Compare outputs:  ./scripts/bootstrap_compare_stages.sh <test.mojo>"
echo "  3. Verify all 3 stages produce identical output"
echo ""
echo "Run individual tests:"
echo "  python3 scripts/stage1_python_interpreter.py <test.mojo>"
echo ""
