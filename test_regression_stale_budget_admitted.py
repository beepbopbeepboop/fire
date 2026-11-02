#!/usr/bin/env python3
"""Regression for bug:TEST_stale_per_child_timeout_literals.
Before the fix test_formal_admitted.py used bare timeout=60 for child runs;
after it uses RUN_TIMEOUT_S / named constants."""

def test_admitted_uses_budget_constants():
    with open('test_formal_admitted.py') as f:
        src = f.read()
    # The child-run budgets must reference the shared constants, not bare ints.
    assert 'RUN_TIMEOUT_S' in src
    assert 'POOL_RESULT_TIMEOUT_S' in src
    assert 'LOCK_TIMEOUT_SUBJECT_S' in src
    assert 'from exec_budget import' in src
    # The executable child budgets (not data-table examples) should be converted.
    # We allow the 5 data-table strings (timeout=30/5/120) to remain.
    from collections import Counter
    import re
    counts = Counter(re.findall(r'timeout=[0-9]+', src))
    assert counts['timeout=60'] == 0, 'bare timeout=60 still present in admitted'

if __name__ == '__main__':
    test_admitted_uses_budget_constants()
    print('test_admitted_uses_budget_constants OK')
