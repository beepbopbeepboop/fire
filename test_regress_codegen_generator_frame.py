"""Regression test for bug:CODEGEN_generator_function_Lib_test_test_frame.
Reproduces the three sub-issues documented in bugs/CODEGEN_generator_function_Lib_test_test_frame.md:
- g: bare BinaryOp (1/0) in generator body -> unsupported expression statement
- gen: yield nested() with sibling nested def -> unresolved callee (fixed:
  a non-capturing sibling is compiled as a helper)
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
    # sibling is a non-capturing sync helper, so the generator must compile
    # it as a static C++ function and call it (not refuse it as an unresolved
    # callee), and the program must run to the helper's value.
    import gimple_codegen as G
    cpp = G.compile_to_gimple_with_cpp(GEN_SRC, do_imports=False)[1]
    assert 'co_yield _mojogen_gen_h_nested();' in cpp, cpp
    assert 'static int64_t _mojogen_gen_h_nested (void) {' in cpp, cpp

def test_regression_gen_sibling_capturing_local_still_refused():
    # The same sibling call, but `nested` reads a local of t0. That is a
    # capture, which the coroutine path has no model for: it must stay
    # refused with the unresolved-callee message, not compile to a helper
    # that names a variable which does not exist in its scope.
    src = (
        'def t0():\n'
        '    k = 5\n'
        '    def nested():\n'
        '        return k\n'
        '    def gen():\n'
        '        yield nested()\n'
        '    g = gen()\n'
        '    return next(g)\n'
        '\n'
        'def main():\n'
        '    print(t0())\n')
    msg = _refusal(src)
    assert msg is not None, 'capturing sibling compiled: the helper must refuse it'
    assert "unresolved callee 'nested(...)'" in msg, msg

def test_regression_g_nested_generator_capturing_self_refused():
    # test_frame.py's `g` (line 95) is a generator defined inside a method
    # that reads the method's `self`. Once the 1/0 statement lowered, this
    # capture is what refuses `g`: the coroutine path has no capture model
    # for a generator defined inside another function. Pinned so the refusal
    # cannot silently disappear; when it compiles, drop this pin and the doc
    # entry together.
    src = (
        'class T:\n'
        '    def run(self):\n'
        '        def g():\n'
        '            yield 1\n'
        '            self.inner()\n'
        '        gen = g()\n'
        '        return next(gen)\n'
        '\n'
        'def main():\n'
        '    print(0)\n')
    msg = _refusal(src)
    assert msg is not None, 'nested generator capturing self compiled: drop this pin'
    assert 'reads enclosing-scope variable(s) self' in msg, msg

def test_regression_t3_async_non_scalar_return():
    # async def t3 returning sys._getframe().f_generator inside a class
    # method: the return type is unknown, so the async return check refuses.
    # Pinned here so the refusal cannot silently disappear.
    msg = _refusal(T3_SRC)
    assert msg is not None, 't3 now compiles: drop this pin and the doc entry'
    assert 't3: every `return` must carry a scalar value' in msg, msg

# bug:CODEGEN_coro_cpp_tuple_for_target_emits_invalid_cpp. A tuple `for`
# target over a literal list of tuples, inside a generator that lowers
# through the C++20-coroutine emitter (MOJO_CORO=cpp), used to emit the
# comma-joined target as one range-for identifier (`for (auto name, den :
# {{1, 2}, {3, 4}})`), which g++ rejects.
TUPLE_LITERAL_SRC = (
    'class Section:\n'
    '    def __init__(self, name: str, n: int):\n'
    '        self.name = name\n'
    '        self.n = n\n'
    '\n'
    'def iter_tables(base: int):\n'
    '    for name, den in [(1, 2), (3, 4)]:\n'
    '        yield Section("sec", name + den + base)\n'
    '\n'
    'def main():\n'
    '    for s in iter_tables(1):\n'
    '        print(s.n)\n')

def _with_cpp_coro(fn):
    # The C++20-coroutine emitter is selected per compile by MOJO_CORO=cpp
    # (the A3 stack-switch backend is the default and never reaches it).
    import os
    old = os.environ.get('MOJO_CORO')
    os.environ['MOJO_CORO'] = 'cpp'
    try:
        return fn()
    finally:
        if old is None:
            del os.environ['MOJO_CORO']
        else:
            os.environ['MOJO_CORO'] = old

def test_regression_tuple_for_target_over_literal_list_binds_per_slot():
    # The loop must bind each slot from its own array, and the generated C++
    # must not contain the comma-joined range-for that g++ rejects.
    import gimple_codegen as G
    _, cpp = _with_cpp_coro(lambda: G.compile_to_gimple_with_cpp(TUPLE_LITERAL_SRC, do_imports=False))
    assert 'for (auto name, den' not in cpp, cpp
    assert 'name = _mg_s_' in cpp and 'den = _mg_s_' in cpp, cpp
    assert 'int64_t name;' in cpp and 'int64_t den;' in cpp, cpp

def test_regression_tuple_for_target_over_literal_list_matches_cpython():
    # Compile, link and run the C++-path program; its stdout must equal the
    # CPython run of the same source (name + den + base for each tuple).
    import subprocess
    import gimple_codegen as G
    import test_gimple_generator_runner as R
    want = subprocess.run(['python3', '-I', '-c', (
        'class Section:\n'
        '    def __init__(self, name, n):\n'
        '        self.name = name\n'
        '        self.n = n\n'
        'def iter_tables(base):\n'
        '    for name, den in [(1, 2), (3, 4)]:\n'
        '        yield Section("sec", name + den + base)\n'
        'for s in iter_tables(1):\n'
        '    print(s.n)\n')], capture_output=True, text=True, timeout=R.RUN_TIMEOUT_S).stdout
    c_code, cpp = _with_cpp_coro(lambda: G.compile_to_gimple_with_cpp(TUPLE_LITERAL_SRC, do_imports=False))
    exe = R._build_generator_program_from_code(c_code, cpp)
    got = subprocess.run([exe], capture_output=True, text=True, timeout=R.RUN_TIMEOUT_S).stdout
    assert got == want, f'CPython {want!r}, compiled {got!r}'

def test_regression_tuple_for_target_over_mixed_literal_refused():
    # Slot 0 is an int in one element and a str in another: no single C type
    # binds it, so the generator refuses honestly instead of guessing.
    src = (
        'def gen():\n'
        '    for a, b in [(1, 2), ("x", 3)]:\n'
        '        yield b\n'
        '\n'
        'def main():\n'
        '    for v in gen():\n'
        '        print(v)\n')
    msg = _with_cpp_coro(lambda: _refusal(src))
    assert msg is not None, 'mixed-kind tuple literal compiled: the slot kinds must be refused'
    assert 'every slot to be one literal kind' in msg, msg
