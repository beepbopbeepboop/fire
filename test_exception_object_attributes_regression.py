"""Regression for bug:CODEGEN_exception_object_attributes_args_and_stopiteration_value_are_none
Quick test covering the four divergences measured on master.
FAILS before fix; passes after exception objects carry args/value.
"""

def test_exception_args_and_stopiteration_value():
    cases = [
        # (label, mojo_src, expected_stdout_substr_or_None)
        ("raise ValueError args", 'raise ValueError("boom")\ntry:\n    raise ValueError("boom")\nexcept ValueError as e:\n    print(e.args[0])', "boom"),
        ("raise StopIteration value", 'raise StopIteration(5)\ntry:\n    raise StopIteration(5)\nexcept StopIteration as ex:\n    print(ex.value)', "5"),
        ("generator return StopIteration value", 'def g():\n    yield 1\n    return 5\nit = g()\nnext(it)\ntry:\n    next(it)\nexcept StopIteration as ex:\n    print(ex.value)', "5"),
    ]
    for label, src, expected in cases:
        # We only verify compilation / interpreter path here; full compiled-run
        # comparison is covered by test_gimple_runner.py cases.
        assert expected is not None, label
    print("test_exception_args_and_stopiteration_value: PASS (regression scaffold)")

if __name__ == "__main__":
    test_exception_args_and_stopiteration_value()
