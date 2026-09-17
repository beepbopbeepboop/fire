"""Interpreter tests for real generator execution — Milestone 2 of
bugs/INTERP_generator_yield_entirely_unimplemented.md.

Milestone 1 (already landed) added PARSER-ONLY support: real
YieldExpr/YieldFromExpr AST nodes and FunctionDef.is_generator /
.yield_bearing_node_ids static marking (see test_yield_parsing.py — that
file covers parsing only, no execution). This file exercises the actual
runtime behavior added on top of that in myinterpreter.py: calling a
generator function must not run any of its body, iterating/`.send()`-ing it
must resume execution up to the next `yield`, `yield from` must delegate
correctly (including return-value propagation), and interleaved generators
must not corrupt each other's local variables (the `interpreter.scope`
single-mutable-attribute hazard — see MojoGeneratorObject's docstring in
myinterpreter.py).
"""
import sys
import fire_compiler as N
from myinterpreter import Interpreter

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def _run(src: str):
    """Parse+execute `src` at module scope, returning the Interpreter (so
    individual tests can pull functions/values back out of its scope)."""
    tokens = N.py_tokenize(src)
    stmts = N.Parser(tokens).parse_module()
    interp = Interpreter()
    for s in stmts:
        interp.execute(s)
    return interp


def _call_main(interp):
    return interp.eval_expr(N.CallExpr(func=N.IdentExpr(name='main')))


def test_call_does_not_run_body():
    interp = _run(
        "ran = False\n"
        "def gen():\n"
        "    global ran\n"
        "    ran = True\n"
        "    yield 1\n"
    )
    gen = interp.scope.get('gen')
    g = gen(interp)
    check("call_returns_without_running_body", interp.scope.get('ran') is False)
    check("call_returns_generator_object", type(g).__name__ == 'MojoGeneratorObject')
    next(g)
    check("first_next_runs_body_up_to_yield", interp.scope.get('ran') is True)


def test_next_and_for_loop():
    interp = _run(
        "def counter():\n"
        "    i = 0\n"
        "    while i < 3:\n"
        "        yield i\n"
        "        i += 1\n"
        "\n"
        "results = []\n"
        "def main():\n"
        "    for x in counter():\n"
        "        results.append(x)\n"
    )
    _call_main(interp)
    check("for_loop_over_generator", interp.scope.get('results') == [0, 1, 2],
          interp.scope.get('results'))


def test_list_of_generator():
    interp = _run(
        "def counter():\n"
        "    i = 0\n"
        "    while i < 4:\n"
        "        yield i\n"
        "        i += 1\n"
    )
    counter = interp.scope.get('counter')
    check("list_consumes_generator", list(counter(interp)) == [0, 1, 2, 3])


def test_yield_in_if_while_for_try():
    interp = _run(
        "def gen(n):\n"
        "    if n > 0:\n"
        "        yield 'pos'\n"
        "    while n > 5:\n"
        "        yield 'big'\n"
        "        n -= 10\n"
        "    for i in range(2):\n"
        "        yield i\n"
        "    try:\n"
        "        yield 'try'\n"
        "    except Exception:\n"
        "        yield 'except'\n"
    )
    gen = interp.scope.get('gen')
    check("yield_in_compound_bodies", list(gen(interp, 7)) == ['pos', 'big', 0, 1, 'try'],
          list(gen(interp, 7)))


def test_send_roundtrip():
    interp = _run(
        "def echo():\n"
        "    x = yield 1\n"
        "    y = yield x + 1\n"
        "    yield y + 1\n"
    )
    echo = interp.scope.get('echo')
    g = echo(interp)
    v1 = next(g)
    v2 = g.send(10)
    v3 = g.send(100)
    check("send_first_value", v1 == 1, v1)
    check("send_echoes_sent_value", v2 == 11, v2)
    check("send_echoes_second_value", v3 == 101, v3)


def test_yield_from_delegation_and_return_value():
    interp = _run(
        "def inner():\n"
        "    yield 1\n"
        "    yield 2\n"
        "    return 99\n"
        "\n"
        "def outer():\n"
        "    r = yield from inner()\n"
        "    yield r\n"
    )
    outer = interp.scope.get('outer')
    check("yield_from_propagates_values_and_return",
          list(outer(interp)) == [1, 2, 99], list(outer(interp)))


def test_yield_from_plain_iterable():
    interp = _run(
        "def gen():\n"
        "    yield from [10, 20, 30]\n"
    )
    gen = interp.scope.get('gen')
    check("yield_from_plain_iterable", list(gen(interp)) == [10, 20, 30])


def test_close_runs_finally():
    interp = _run(
        "cleaned_up = False\n"
        "def gen():\n"
        "    global cleaned_up\n"
        "    try:\n"
        "        yield 1\n"
        "        yield 2\n"
        "    finally:\n"
        "        cleaned_up = True\n"
    )
    gen = interp.scope.get('gen')
    g = gen(interp)
    next(g)
    check("not_cleaned_up_before_close", interp.scope.get('cleaned_up') is False)
    g.close()
    check("close_runs_finally_cleanup", interp.scope.get('cleaned_up') is True)


def test_exception_in_generator_caught_by_caller():
    interp = _run(
        "def bad():\n"
        "    yield 1\n"
        "    raise Error('boom')\n"
        "\n"
        "caught_msg = None\n"
        "def main():\n"
        "    global caught_msg\n"
        "    g = bad()\n"
        "    next(g)\n"
        "    try:\n"
        "        next(g)\n"
        "    except Exception as e:\n"
        "        caught_msg = str(e)\n"
    )
    _call_main(interp)
    check("exception_propagates_to_caller", interp.scope.get('caught_msg') == 'boom',
          interp.scope.get('caught_msg'))


def test_interleaved_generators_dont_share_scope():
    interp = _run(
        "def make(start):\n"
        "    x = start\n"
        "    while True:\n"
        "        yield x\n"
        "        x = x + 1\n"
    )
    make = interp.scope.get('make')
    g1 = make(interp, 100)
    g2 = make(interp, 200)
    seq = [next(g1), next(g2), next(g1), next(g2), next(g1), next(g2)]
    check("interleaved_generators_keep_separate_scope",
          seq == [100, 200, 101, 201, 102, 202], seq)


def test_generator_method_on_struct():
    interp = _run(
        "struct Counter:\n"
        "    var n: Int\n"
        "    def __init__(out self, n: Int):\n"
        "        self.n = n\n"
        "    def gen(self):\n"
        "        i = 0\n"
        "        while i < self.n:\n"
        "            yield i\n"
        "            i += 1\n"
        "\n"
        "def main():\n"
        "    c = Counter(3)\n"
        "    return list(c.gen())\n"
    )
    result = _call_main(interp)
    check("generator_bound_method", result == [0, 1, 2], result)


def test_stopiteration_after_exhaustion():
    interp = _run(
        "def gen():\n"
        "    yield 1\n"
    )
    gen = interp.scope.get('gen')
    g = gen(interp)
    next(g)
    try:
        next(g)
        check("stopiteration_after_exhaustion", False, "did not raise")
    except StopIteration:
        check("stopiteration_after_exhaustion", True)


def run_tests():
    for fn in [
        test_call_does_not_run_body,
        test_next_and_for_loop,
        test_list_of_generator,
        test_yield_in_if_while_for_try,
        test_send_roundtrip,
        test_yield_from_delegation_and_return_value,
        test_yield_from_plain_iterable,
        test_close_runs_finally,
        test_exception_in_generator_caught_by_caller,
        test_interleaved_generators_dont_share_scope,
        test_generator_method_on_struct,
        test_stopiteration_after_exhaustion,
    ]:
        try:
            fn()
        except Exception as e:
            global _FAIL
            _FAIL += 1
            print(f"FAIL  {fn.__name__}  raised {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    ok = run_tests()
    sys.exit(0 if ok else 1)
