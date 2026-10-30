"""Regression test for bug:CODEGEN_generator_function_Lib_test_test_frame.
Reproduces the three sub-issues documented in bugs/CODEGEN_generator_function_Lib_test_test_frame.md:
- g: bare BinaryOp (1/0) in generator body -> unsupported expression statement
- gen: yield nested() with sibling nested def -> unresolved callee
- t3: async return of non-scalar (frame.f_generator) -> cross-path return unification
Current master (work/bug-codegen-generator-function-lib-test-362, HEAD 7cbacac97)
still refuses all three per the 2026-09-07 doc verification.
"""

def test_regression_g_bare_binaryop_in_generator():
    # g's bare `1/0` statement: the divisor is a runtime mojo_int_divisor
    # check (raises ZeroDivisionError), and a bare expression statement is
    # lowered in the coroutine body. The real assertion lives beside the
    # integer-division tests.
    from test_codegen_int_div_zero import test_bare_zero_division_statement_in_generator
    test_bare_zero_division_statement_in_generator()

def _refusal(src):
    # Compile through the real entry point and return the refusal text, or
    # None if the module compiled. Both shapes below are expected to refuse
    # until the feature in the doc's Status lands; a pass here would mean the
    # refusal went away, which the assertion below then reports.
    import gimple_codegen as G
    try:
        G.compile_to_gimple_with_cpp(src, do_imports=False)
    except RuntimeError as e:
        return str(e)
    return None

GEN_SRC = (
    'def t0():\n'
    '    def nested():\n'
    '        return 1\n'
    '    def gen():\n'
    '        yield nested()\n'
    '    g = gen()\n'
    '    return next(g)\n'
    '\n'
    'def main():\n'
    '    print(t0())\n')

T3_SRC = (
    'import sys\n'
    'import unittest\n'
    'class T(unittest.TestCase):\n'
    '    def test_f(self):\n'
    '        async def t3():\n'
    '            frame = sys._getframe()\n'
    '            return frame.f_generator\n'
    '        c = t3()\n'
    '        return 0\n'
    '\n'
    'def main():\n'
    '    print(0)\n')

def test_regression_gen_nested_def_yield():
    # yield nested() where nested is a sibling nested def inside t0. The
    # callee is a callable-value local (cluster A in the doc); the refusal
    # must name it, not fall through to a generic whole-module message.
    msg = _refusal(GEN_SRC)
    assert msg is not None, 'gen now compiles: drop this pin and the doc entry'
    assert "unresolved callee 'nested(...)'" in msg, msg

def test_regression_t3_async_non_scalar_return():
    # async def t3 returning sys._getframe().f_generator inside a class
    # method: the return type is unknown, so the async return check refuses.
    # Pinned here so the refusal cannot silently disappear.
    msg = _refusal(T3_SRC)
    assert msg is not None, 't3 now compiles: drop this pin and the doc entry'
    assert 't3: every `return` must carry a scalar value' in msg, msg
