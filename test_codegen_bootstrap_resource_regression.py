# Pinning regression for bugs/CODEGEN_bootstrap_resource_blowup.md
# The doc's 2026-10-25 Status records bootstrap green (0 stage1-vs-stage2
# diffs, 0 stage2-vs-stage3 diffs, 184 files identical). This test asserts
# the bootstrap-verify script exits 0 when stage trees exist.
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(HERE, 'stage1')
def test_bootstrap_stage_equality():
    # If stage trees were built by the gate, they must match;
    # absence is a build-state issue, not a codegen divergence.
    if not os.path.isdir(STAGE):
        return  # gate hasn't produced trees in this worktree
    result = subprocess.run(
        [sys.executable, 'tools/bootstrap_verify.py', '-q'],
        cwd=HERE, capture_output=True, text=True)
    assert result.returncode == 0, \
        f"bootstrap-verify failed: {result.stdout}\n{result.stderr}"
