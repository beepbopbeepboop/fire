"""Integer division by zero raises ZeroDivisionError on the compiled path.

Before this, `x // 0`, `x / 0` and `x % 0` lowered to a bare C division, which
on arm64 silently answers 0 — so `try: ... except ZeroDivisionError:` never
fired. Both lowerings now route the divisor through `mojo_int_divisor`
(runtime/fire_runtime.h), which raises. The generator case is the bare
expression statement `1/0` from Lib/test/test_frame.py's `g`.
"""
import subprocess, sys, os

def run_jit(src):
    p = '.tmp/_int_div_zero.mojo'
    os.makedirs('.tmp', exist_ok=True)
    with open(p, 'w') as f:
        f.write(src)
    r = subprocess.run([sys.executable, 'fire.py', '--jit', p],
                       capture_output=True, text=True)
    return r.stdout.strip(), r.returncode

def test_zero_divisor_raises_in_plain_function():
    src = ('def main():\n'
           '    x = 7\n'
           '    y = 0\n'
           '    try:\n'
           '        z = x // y\n'
           '        print("no exception", z)\n'
           '    except ZeroDivisionError:\n'
           '        print("caught floordiv")\n'
           '    try:\n'
           '        w = x / y\n'
           '        print("no exception", w)\n'
           '    except ZeroDivisionError:\n'
           '        print("caught div")\n'
           '    try:\n'
           '        v = x % y\n'
           '        print("no exception", v)\n'
           '    except ZeroDivisionError:\n'
           '        print("caught mod")\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == 'caught floordiv\ncaught div\ncaught mod', repr(out)

def test_nonzero_integer_division_unchanged():
    # Nonzero divisors must still divide as before. `8 / b` is true division,
    # which answers the Float64 `4.0` (see test_int_true_division_is_float).
    src = ('def main():\n'
           '    a = 7\n'
           '    b = 2\n'
           '    n = -7\n'
           '    print(a // b, a % b, n // b, 8 / b)\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == '3 1 -4 4.0', repr(out)

def test_int_true_division_is_float():
    # Int / Int is true division, a Float64 in Python and Mojo: `7 / 2` is
    # 3.5, not the C integer quotient 3. Locals, literals and a computed
    # operand all take the same path.
    src = ('def main():\n'
           '    a = 7\n'
           '    b = 2\n'
           '    print(a / b, 8 / 4, a / 4, (a + 1) / b)\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == '3.5 2.0 1.75 4.0', repr(out)

def test_integer_modulo_floors_toward_divisor_sign():
    # Python's int `%` takes the divisor's sign (floor), where C's truncates.
    # The plain `%` lowering must correct a nonzero remainder whose sign
    # differs from the divisor's, for both `%` and `%=`.
    src = ('def main():\n'
           '    n = -7\n'
           '    p = 7\n'
           '    q = -2\n'
           '    e = -8\n'
           '    t = 3\n'
           '    print(n % 2, p % q, n % q, e % t, p % 2)\n'
           '    m = -7\n'
           '    m %= 2\n'
           '    print(m)\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == '1 -1 -1 1 1\n1', repr(out)

def test_integer_modulo_floors_in_generator_body():
    # The same `%` inside a compiled generator (the `*, start=[]` shape that
    # gets a C++20 coroutine unit) takes the coroutine emitter's lowering in
    # cpp_core.py, which must floor exactly as the plain GIMPLE path does.
    src = ('def g(*, start=[]):\n'
           '    n = -7\n'
           '    yield n % 2\n'
           '    yield 7 % -2\n'
           'def main():\n'
           '    for v in g():\n'
           '        print(v)\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == '1\n-1', repr(out)

def test_bare_zero_division_statement_in_generator():
    # test_frame.py's `g`: a bare `1/0` expression statement inside a try in a
    # generator body. It must raise (and so be caught), not be refused.
    src = ('def g():\n'
           '    try:\n'
           '        1/0\n'
           '    except ZeroDivisionError:\n'
           '        yield 1\n'
           '    yield 2\n'
           'def main():\n'
           '    for v in g():\n'
           '        print(v)\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == '1\n2', repr(out)

if __name__ == '__main__':
    test_zero_divisor_raises_in_plain_function()
    test_nonzero_integer_division_unchanged()
    test_int_true_division_is_float()
    test_integer_modulo_floors_toward_divisor_sign()
    test_integer_modulo_floors_in_generator_body()
    test_bare_zero_division_statement_in_generator()
    print("OK")
