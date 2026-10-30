"""Regression for randdec tuple-yield fix: fixed-arity tuple yield must compile."""
import gimple_codegen
# Fixed-arity tuple yields (the shape randdec's refused generators used)
# must compile through the coroutine emitter rather than be refused.
src = "def g():\n    yield (1, 2)\n    yield (3, 4, 5)\n"
try:
    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(src, do_imports=False)
    assert c_code or cpp_code, "expected generated code"
    print("PASS randdec_tuple_yield_regression")
except Exception as e:
    print("FAIL", e)
    raise
