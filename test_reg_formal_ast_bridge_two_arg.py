#!/usr/bin/env python3
"""Regression for FORMAL_ast_bridge_cannot_state_a_user_call_of_two_or_more_arguments.

The AST bridge now builds a callFunc2 branch for every two-parameter callee
whose model is emitted, and includes those names in resolvable2 so the gap
check passes rather than refusing.
"""
import os, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_formal_call_proof_gen import _generate, _functions

def test_two_arg_callee_builds_with_bridge():
    src = ("def _scalar_max2(a, b):\n"
           "    if a > b:\n"
           "        return a\n"
           "    return b\n"
           "def main(x):\n"
           "    return _scalar_max2(x, x)\n")
    tmp = tempfile.mkdtemp(prefix="reg-a2-")
    try:
        p, err = _generate(tmp, src, "reg_two_arg")
        assert err is None, f"must build, got refusal: {err}"
        assert p is not None
        text = open(p).read()
        assert "eval_eq_mojo" in text, "benchmark theorem must be present"
        assert "callFunc2" in text or "_scalar_max2_go" in text, \
            "two-param callee must reach callFunc2"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    test_two_arg_callee_builds_with_bridge()
    print("PASS: regression for two-argument user-call bridge")
