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
    # Nonzero divisors must still divide as before. `7 / 2` and `-7 % 2` are
    # left out on purpose: this compiler's int `/` truncates where Python's is
    # a float, and its `%` truncates where Python's floors — separate defects,
    # not part of the zero-divisor check (see bugs/CODEGEN_int_mod_negative_truncates.md).
    src = ('def main():\n'
           '    a = 7\n'
           '    b = 2\n'
           '    n = -7\n'
           '    print(a // b, a % b, n // b, 8 / b)\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == '3 1 -4 4', repr(out)

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
    test_bare_zero_division_statement_in_generator()
    print("OK")
