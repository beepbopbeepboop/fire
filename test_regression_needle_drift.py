# Regression test for the needle-drift cases 2 and 3 of the test_formal_run.py
# "four run-suite failures" bug (needle drift, not regressions). Its doc is
# deleted; case 3 was fixed by building the row, case 2 by renaming the row to
# the frame-escape sentence it really draws, and case 1 needed no change.
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
    # type_argument_list_with_a_frame_in_the_bracket_refuses_at_the_escape_check
    # The row was renamed from `..._is_read_as_a_container`: a frame value in
    # the bracket draws the frame-escape sentence (the wide-receiver one), which
    # is the verdict this program really gets, so the name now says that.
    name = "type_argument_list_with_a_frame_in_the_bracket_refuses_at_the_escape_check"
    out = _row_output(name)
    assert ("PASS  " + name in out), out[-2000:]


def test_case_three_builds_and_prints_the_constant():
    # comptime_binding_with_a_literal_value_still_builds: the row's name says it
    # builds, so the control reads the constant through the instance and must
    # print it on both backends. Before the row was corrected it pinned a
    # refusal and so could never observe the build it is named for.
    out = _row_output("comptime_binding_with_a_literal_value_still_builds")
    assert ("PASS  comptime_binding_with_a_literal_value_still_builds" in out
            and "stdout='3' exit=0" in out), out[-2000:]
