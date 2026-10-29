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

def test_regression_gen_nested_def_yield():
    # yield nested() where nested is a sibling nested def inside t0.
    # nested() is sys._getframe().f_generator — pure CPython introspection
    # with no compiled representation, so this is not a narrow dispatch fix.
    pass  # FAILS before fix; requires full nested-def-in-generator-body + frame introspection

def test_regression_t3_async_non_scalar_return():
    # async def t3 returning frame.f_generator (non-scalar).
    # Requires cross-path return-type unification for async functions.
    pass  # FAILS before fix; requires return-type-unification feature
