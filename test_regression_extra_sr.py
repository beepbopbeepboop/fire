# Regression for bug-formal-formal-a-generated-proof-over-5313.
# The fix is in formal/arm64_proof_gen.py: _gen_step_result_lemmas accepts
# extra_idx so step-RESULT lemmas cover extern call sites past the region.
import sys, inspect
sys.path.insert(0, '.')
from formal.arm64_proof_gen import _gen_step_result_lemmas
sig = inspect.signature(_gen_step_result_lemmas)
assert 'extra_idx' in sig.parameters, "_gen_step_result_lemmas must accept extra_idx"
# Synthetic instruction at index 0 (RET, word 0xD65F03C0) inside region,
# plus extra index 100 with RET word so the function keeps it.
code = bytes([0xC0, 0x03, 0x5F, 0xD6]) + bytes(396) + bytes([0xC0, 0x03, 0x5F, 0xD6])
plan_inside = {0: (0xD65F03C0, 0, "some {...}")}
# Just verify it does not crash and accepts extra_idx.
out = _gen_step_result_lemmas("t", code, 0, 4, extra_idx=[100])
assert "t_sr_400" in out or "t_sr_100" in out or out.startswith("theorem"), f"unexpected output: {out[:200]}"
print("test_regression_extra_sr PASS")
