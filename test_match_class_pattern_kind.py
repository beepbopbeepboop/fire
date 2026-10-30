# Regression test for the class-pattern kind (bug COMPILE_FAIL_Tools_cases_generator_analyzer).
# `case C():` is a type test and gets its own kind, which the compiled path
# lowers as isinstance. Any sub-pattern (`C(x)`, `C(x=0)`) still deconstructs
# the subject and stays "class pattern" (refused) until __match_args__ is bound.

import sys
sys.path.insert(0, '.')
import fire_compiler as F
from formal import model

# Zero-arg class pattern: the type test
pat0 = F.CallExpr(func=F.IdentExpr('Point'), args=[])
kind0 = model.match_pattern_kind(pat0)
assert kind0 == "class pattern (type test)", f"expected type test, got {kind0}"

# Positional sub-pattern: deconstruction, still refused
pat_cap = F.CallExpr(func=F.IdentExpr('Point'), args=[F.IdentExpr('x')])
kind_cap = model.match_pattern_kind(pat_cap)
assert kind_cap == "class pattern", f"expected refused class pattern, got {kind_cap}"

# Keyword sub-pattern: deconstruction, still refused
pat_kw = F.CallExpr(func=F.IdentExpr('Point'), args=[], kwargs=[('x', F.IntLiteral(0))])
kind_kw = model.match_pattern_kind(pat_kw)
assert kind_kw == "class pattern", f"expected refused class pattern, got {kind_kw}"

# The formal layer refuses the type test, and must have a message for it
assert "class pattern (type test)" in model.MATCH_REFUSED_KINDS
msg = model.match_pattern_refusal("class pattern (type test)", "Point()", "f", 1)
assert "CLASS TYPE TEST" in msg, msg

print("PASS: class-pattern kinds recognized")
