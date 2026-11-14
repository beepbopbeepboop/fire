"""Regression for bug:TEST_stale_per_child_timeout_literals: test_gimple.py sites."""

def test_gimple_uses_shared_constants_at_named_sites():
    import ast, os
    here = os.path.dirname(__file__)
    src = open(os.path.join(here, 'test_gimple.py'), 'r').read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == 'timeout':
                    val = kw.value
                    if isinstance(val, ast.Constant) and isinstance(val.value, int):
                        # Lines 7979/7981 previously had literals 600/60; after fix
                        # they must read COMPILE_TIMEOUT_S / RUN_TIMEOUT_S (names).
                        pass
    # The real check: the two named call sites must not be integer literals.
    # We verify by reading the source at those lines directly.
    lines = src.splitlines()
    # Line numbers are 1-based
    assert 'COMPILE_TIMEOUT_S' in lines[7978], 'line 7979 should use COMPILE_TIMEOUT_S'
    assert 'RUN_TIMEOUT_S' in lines[7980], 'line 7981 should use RUN_TIMEOUT_S'
