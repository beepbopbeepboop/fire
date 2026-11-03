#!/usr/bin/env python3
"""Pin for bug-test-stale-per-child-timeout-literal-3915: the budget census
must stay reconciled (no stale literals in adopted files, residue not growing)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_suite import (test_no_stale_per_child_budget_is_left_as_a_literal,
                        STALE_PER_CHILD_BUDGETS, BUDGET_IS_THE_SUBJECT)
# The check is pure-python synthetic; run the census portion directly.
# If anyone reverts the exec_budget conversions this fails.
test_no_stale_per_child_budget_is_left_as_a_literal()
print('PASS budget_regression_pin')
