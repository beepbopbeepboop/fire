# Regression test for class-pattern type test (bug-compile-fail-tools-cases-generator-a)
# Before fix: formal/model.match_pattern_kind returned "class pattern" (refused).
# After fix: it returns "class pattern (type test)" for zero-arg / positional captures.

import sys
sys.path.insert(0, '.')
import fire_compiler as F
from formal import model

# Zero-arg class pattern
pat0 = F.CallExpr(func=F.IdentExpr('Point'), args=[])
kind0 = model.match_pattern_kind(pat0)
assert kind0 == "class pattern (type test)", f"expected new kind, got {kind0}"

# Positional capture pattern (minimal check: the new kind is used for args-only)
pat_cap = F.CallExpr(func=F.IdentExpr('Point'), args=[F.IdentExpr('x')])
kind_cap = model.match_pattern_kind(pat_cap)
# Before fix this was refused; after fix it should be allowed
assert kind_cap == "class pattern (type test)", f"expected new kind for capture, got {kind_cap}"

print("PASS: class-pattern kind recognized")
