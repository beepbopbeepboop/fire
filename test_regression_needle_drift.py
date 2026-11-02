# Regression test for needle-drift cases 2 and 3 from
# bugs/RUN_four_run_suite_failures_that_are_needle_drift_not_regressions.md
#
# Each check runs the named row of test_formal_run.py through the real
# build-and-run harness and reads its verdict line. A row that refuses where
# its name says it builds (case 3) or draws a different sentence than its
# needle (case 2) prints FAIL for that row, so these fail on a stale row and
# pass on a correct one. They are subprocess checks rather than string
# comparisons: the earlier version asserted `msg in msg`, which can never fail.

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FORMAL_RUN = os.path.join(HERE, "test_formal_run.py")


def _row_output(name):
    proc = subprocess.run(
        [sys.executable, FORMAL_RUN, "-v", name],
        cwd=HERE, capture_output=True, text=True, timeout=900,
    )
    return proc.stdout + proc.stderr


def test_case_two_refusal_message():
    # type_argument_list_on_a_generic_struct_of_this_unit_is_read_as_a_container
    # Pinned to the wide-receiver sentence the construct measures today.
    out = _row_output(
        "type_argument_list_on_a_generic_struct_of_this_unit_is_read_as_a_container")
    assert ("PASS  type_argument_list_on_a_generic_struct_of_this_unit_is_read_as_a_container"
            in out), out[-2000:]


def test_case_three_builds_and_prints_the_constant():
    # comptime_binding_with_a_literal_value_still_builds: the row's name says it
    # builds, so the control reads the constant through the instance and must
    # print it on both backends. Before the row was corrected it pinned a
    # refusal and so could never observe the build it is named for.
    out = _row_output("comptime_binding_with_a_literal_value_still_builds")
    assert ("PASS  comptime_binding_with_a_literal_value_still_builds" in out
            and "stdout='3' exit=0" in out), out[-2000:]
