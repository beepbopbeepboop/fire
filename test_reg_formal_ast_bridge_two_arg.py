#!/usr/bin/env python3
"""Regression for FORMAL_ast_bridge_cannot_state_a_user_call_of_two_or_more_arguments.

The AST bridge now builds a callFunc2 branch for every two-parameter callee
whose model is emitted, and includes those names in resolvable2 so the gap
check passes rather than refusing.

Also pins FORMAL_concrete_eval_eq_mojo_instances_omit_the_two_arg_env: the
concrete `eval_eq_mojo_*` instances must pass the same two-argument call
environment as the universal theorem, so Lean accepts the proof.
"""
import os, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_formal_call_proof_gen import _generate, _check_proof


_TWO_ARG_SRC = (
    "def _scalar_max2(a, b):\n"
    "    if a > b:\n"
    "        return a\n"
    "    return b\n"
    "def main(x):\n"
    "    return _scalar_max2(x, x)\n"
)


def test_two_arg_callee_builds_with_bridge():
    tmp = tempfile.mkdtemp(prefix="reg-a2-")
    try:
        p, err = _generate(tmp, _TWO_ARG_SRC, "reg_two_arg")
        assert err is None, f"must build, got refusal: {err}"
        assert p is not None
        text = open(p).read()
        assert "eval_eq_mojo" in text, "benchmark theorem must be present"
        assert "callFunc2" in text or "_scalar_max2_go" in text, \
            "two-param callee must reach callFunc2"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_two_arg_callee_concrete_eval_eq_mojo_checks():
    """The concrete eval_eq_mojo instances must state the two-arg env."""
    tmp = tempfile.mkdtemp(prefix="reg-a2c-")
    try:
        p, err = _generate(tmp, _TWO_ARG_SRC, "reg_two_arg")
        assert err is None, f"must build, got refusal: {err}"
        got = _check_proof(p)
        if got is None:
            return  # skipped without Lean / ProofLib.olean
        ok, detail, _n = got
        assert ok, f"proof must check (concrete eval_eq_mojo instances): {detail}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_two_arg_callee_builds_with_bridge()
    test_two_arg_callee_concrete_eval_eq_mojo_checks()
    print("PASS: regression for two-argument user-call bridge")
