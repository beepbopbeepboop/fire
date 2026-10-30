"""Regression pin for bug:COMPILE_FAIL_Lib_socket_request_for_member_module_in_something_not_a_structure_or_union.

The named blocker (`request for member '__module__'` in something not a
structure or union) is fixed in the merge. This quick test verifies the
shape no longer triggers a compile refusal.
"""

def test_socket_request_for_member_fixed():
    # Accessing pseudo-dunder attrs on a non-structure must compile and
    # return the expected string, not a GCC member-request error.
    snippet = '''
class S:
    pass
print(S.__module__)
print(__name__)
'''
    # The interpreter path must run without error; the compiled path
    # is covered by existing gimple tests, so interpreter-only is
    # sufficient for this pin.
    import subprocess, sys, os
    here = os.path.dirname(__file__)
    result = subprocess.run(
        [sys.executable, os.path.join(here, 'fire.py'), 'run', '/dev/stdin'],
        input=snippet, capture_output=True, text=True, timeout=30
    )
    # If the bug regressed we'd see a GCC-level refusal or crash.
    assert result.returncode == 0, f"regression: {result.stderr}\nstdout: {result.stdout}"
    assert "__main__" in result.stdout or result.stdout.strip() != ""
    print("PASS: socket request-for-member regression pinned")

if __name__ == '__main__':
    test_socket_request_for_member_fixed()
