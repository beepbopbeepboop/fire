"""Pinning regression for CODEGEN_callable_return_type_lost_at_more_hops.
Already fixed in gimple_codegen.py (CLOSED 2026-10-02); this prevents regression."""
from test_gimple_runner import test_gimple_matches_cpython

def test_callable_return_type_and_bound_method_convention_pinned():
    test_gimple_matches_cpython("pin_callable_return_type_at_more_hops", """\
def a():
    e = lambda: False
    return e
def c():
    e = a()
    print(e())
c()
""")
    test_gimple_matches_cpython("pin_bound_method_global_convention", """\
class C:
    def truthy(self): return True
m = C()
f = m.truthy
print(f())
""")
