"""A coroutine's loop over an int-element list parameter reads the loop
variable as an int, not as the `char *` the runtime dict-or-list dispatch
declares first. See bugs/CODEGEN_coro_list_param_int_element_loop_target_is_char_pointer.md.

The parameter crosses the stack-switch ABI as a boxed int64_t handle, so the
ordinary `for` lowering emits the dict/list dispatch; both arms bind one
loop variable. The producer knows the element is int (the unanimous call-site
contract), and that positive evidence has to reach the dispatch to skip the
dict arm. Before the fix the printed values were pointer bits.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gimple_codegen  # noqa: E402


def run_jit(src):
    p = os.path.join(HERE, '.tmp', '_coro_list_param_int_element.mojo')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write(src)
    r = subprocess.run([sys.executable, 'fire.py', '--jit', p],
                       capture_output=True, text=True, cwd=HERE)
    return r.stdout.strip(), r.returncode


def test_generator_loop_over_int_list_param_does_arithmetic():
    src = ('def gen_add(xs):\n'
           '    for x in xs:\n'
           '        yield x + 100\n'
           '\n'
           'def main():\n'
           '    for v in gen_add([4, 5]):\n'
           '        print(v)\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == '104\n105', repr(out)


def test_generator_loop_over_star_args_does_arithmetic():
    src = ('def gen_star(*xs):\n'
           '    for x in xs:\n'
           '        yield x + 100\n'
           '\n'
           'def main():\n'
           '    for v in gen_star(1, 2, 3):\n'
           '        print(v)\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == '101\n102\n103', repr(out)


def test_plain_function_list_param_unchanged():
    # Not a coroutine: the same loop over a list parameter must keep working
    # through the ordinary cross-call element contract.
    src = ('def plain_sum(xs):\n'
           '    var t = 0\n'
           '    for x in xs:\n'
           '        t += x\n'
           '    return t\n'
           '\n'
           'def main():\n'
           '    print(plain_sum([4, 5]))\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == '9', repr(out)


def test_generator_enumerate_over_int_list_param_does_arithmetic():
    # `enumerate(<param>)` shares `_boxed_list_ptr` with the bare `for`, so
    # the same positive evidence must reach its element read too.
    src = ('def gen_en(xs):\n'
           '    for i, x in enumerate(xs):\n'
           '        yield i * 1000 + x + 100\n'
           '\n'
           'def main():\n'
           '    for v in gen_en([4, 5]):\n'
           '        print(v)\n')
    out, rc = run_jit(src)
    assert rc == 0, out
    assert out == '104\n1105', repr(out)


def test_async_star_args_loop_target_is_not_dispatched():
    # An `async def` (not a generator) reads its list param through the same
    # untyped slots, so it needs the same contract. Its driver (asyncio.run
    # on a compiled coroutine) is not yet exercised by any quick test, so the
    # check is structural: the body must not carry the dict-or-list dispatch
    # for `x`, and `x` must be declared as the int it is.
    src = ('async def total(*xs):\n'
           '    var t = 0\n'
           '    for x in xs:\n'
           '        t += x\n'
           '    return t\n'
           '\n'
           'async def main():\n'
           '    var r = await total(1, 2, 3)\n'
           '    print(r)\n')
    c = gimple_codegen.compile_to_gimple(src, do_imports=False, filename='async_total.mojo')
    start = c.index('void __mgco_total_body (int64_t __c)')
    body = c[start:c.index('\n}\n', start)]
    assert 'char * x;' not in body, 'loop target declared as char * (dict arm won)'
    assert 'mojo_is_registered_dict' not in body, 'dict-or-list dispatch was emitted'
    assert 'int64_t x;' in body, 'loop target not declared as int64_t'
