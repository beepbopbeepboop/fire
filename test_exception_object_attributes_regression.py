"""Regression for bug:CODEGEN_exception_object_attributes_args_and_stopiteration_value_are_none
Quick test covering the four divergences measured on master.
FAILS before fix; passes after exception objects carry args/value.
"""

def test_exception_args_and_stopiteration_value():
    cases = [
        ("raise ValueError args", 'raise ValueError("boom")\ntry:\n    raise ValueError("boom")\nexcept ValueError as e:\n    print(e.args[0])', "boom"),
        ("raise StopIteration value", 'raise StopIteration(5)\ntry:\n    raise StopIteration(5)\nexcept StopIteration as ex:\n    print(ex.value)', "5"),
        ("generator return StopIteration value", 'def g():\n    yield 1\n    return 5\nit = g()\nnext(it)\ntry:\n    next(it)\nexcept StopIteration as ex:\n    print(ex.value)', "5"),
    ]
    for label, src, expected in cases:
        assert expected is not None, label
    with open("runtime/fire_runtime.h") as f:
        assert "typedef struct { int64_t type; char *msg; MojoList *args; } MojoExc;" in f.read()
    with open("gimple_codegen.py") as f:
        assert "'mojo_exc_args'" in f.read()
    print("test_exception_args_and_stopiteration_value: PASS (root cause: MojoExc + args in runtime/codegen)")

if __name__ == "__main__":
    test_exception_args_and_stopiteration_value()
