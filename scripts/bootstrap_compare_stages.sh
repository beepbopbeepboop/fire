#!/bin/bash
# Compare Stage 1 (Python) vs Stage 2 (Mojo) outputs
# Usage: ./scripts/bootstrap_compare_stages.sh <test.mojo>

set -euo pipefail

STAGE1="scripts/stage1_python_interpreter.py"
STAGE2="scripts/stage2_mojo_interpreter.mojo"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <test.mojo>" >&2
    exit 1
fi

TEST_FILE="$1"
TEST_NAME=$(basename "$TEST_FILE" .mojo)

echo "======================================================================="
echo "STAGE COMPARISON: $TEST_NAME"
echo "======================================================================="

# Run Stage 1
echo "Running Stage 1 (Python)..."
python3 "$STAGE1" "$TEST_FILE" > "/tmp/stage1_$TEST_NAME.c" 2>/tmp/stage1_$TEST_NAME.err
STAGE1_SIZE=$(wc -l < "/tmp/stage1_$TEST_NAME.c")
echo "  Output: $STAGE1_SIZE lines"

# Try Stage 2
if command -v mojo &> /dev/null; then
    echo "Running Stage 2 (Mojo)..."
    mojo run "$STAGE2" "$TEST_FILE" > "/tmp/stage2_$TEST_NAME.c" 2>/tmp/stage2_$TEST_NAME.err
    STAGE2_SIZE=$(wc -l < "/tmp/stage2_$TEST_NAME.c")
    echo "  Output: $STAGE2_SIZE lines"

    # Compare
    echo ""
    if diff -q "/tmp/stage1_$TEST_NAME.c" "/tmp/stage2_$TEST_NAME.c" > /dev/null; then
        echo "✓ STAGE 1 ≡ STAGE 2 (byte-for-byte identical)"
        echo "  Bootstrap determinism verified!"
    else
        echo "✗ STAGE 1 ≠ STAGE 2"
        echo "  Differences:"
        diff "/tmp/stage1_$TEST_NAME.c" "/tmp/stage2_$TEST_NAME.c" | head -20
    fi
else
    echo "⊘ Mojo not available - skipping Stage 2"
    echo "  Stage 1 output saved to: /tmp/stage1_$TEST_NAME.c"
fi

echo ""
echo "======================================================================="
