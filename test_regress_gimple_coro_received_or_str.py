# Regression: CPP coroutine tagged-word/string `or` path must pass the
# boxed string word payload (not the raw tagged word pointer) to string
# consumers like concatenation. `(x or '') + 'z'` where x is a received
# tagged string/None word must behave as in CPython.
# (SUITE_gimplegenerators received_or_str_operand_cpp, fixed on this branch)

import test_gimple_generator_runner as t


if __name__ == "__main__":
    with t.coro.pinned("cpp"):
        t.test_generator_matches_cpython(
            "received_or_str_operand_cpp",
            t._RECEIVED_OR_STR_SRC,
            t._RECEIVED_OR_STR_SRC,
        )
    if t._FAIL:
        raise SystemExit(1)
    print("ok")
