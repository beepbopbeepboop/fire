# Regression for bug:FORMAL_arm64_the_shifted_register_arm_ignores_its_shift
# The SUBS (shifted register) arm 0xeb000000 and ADDS/CMN 0xab000000
# must apply the shift from bits 23:22 and 15:10.

# Minimal check: the proof-gen _step_rhs for index 6 includes <<<
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import formal.arm64_proof_gen as p
rhs6 = p._step_rhs(0xeb021023, 6)
assert "<<<" in rhs6, f"_step_rhs index 6 missing shift: {rhs6}"
print("PASS: _step_rhs index 6 includes shift")

# Also verify ADD (already fixed) and SUB (already fixed) use shift
rhs2 = p._step_rhs(0x8b021023, 2)
assert "<<<" in rhs2
rhs3 = p._step_rhs(0xcb021023, 3)
assert "<<<" in rhs3
print("PASS: _step_rhs indices 2/3 include shift")
