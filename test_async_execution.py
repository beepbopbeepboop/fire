"""Interpreter tests for real async/await execution — Milestone 3b of
INTERP_generator_yield_entirely_unimplemented.

Milestone 3a (already landed) added PARSER-ONLY support: real AwaitExpr /
FunctionDef.is_async / ForStmt.is_async / WithStmt.is_async static marking
(see test_async_parsing.py — parsing only, no execution). This file
exercises the actual runtime behavior added on top of that in
myinterpreter.py: calling an `async def` function must not run any of its
body, `await` must correctly drive both Mojo-to-Mojo coroutine chains and
REAL native asyncio awaitables (asyncio.sleep, asyncio.gather, real
sockets' event-loop machinery), and concurrent Mojo coroutines driven by
the real asyncio event loop must not corrupt each other's local variables
(the same `interpreter.scope` single-mutable-attribute hazard already
handled for generators — see MojoCoroutine's docstring in
myinterpreter.py — but now under GENUINE concurrency, not just
hand-interleaved single-thread stepping).

The core validated claim (see MojoCoroutine/`_RealAwaitStep`/
`_RealThreadCall` docstrings for the full mechanism): a `MojoCoroutine` is
a real, protocol-compliant Python awaitable — `asyncio.run(mojo_coro)`,
`await mojo_coro` from ordinary real Python code, and `asyncio.gather(...)`
of several Mojo coroutines all work against real asyncio's real event
loop, with real wall-clock timing and real concurrency, not a synchronous
approximation.
"""
import asyncio
import sys
import time
import fire_compiler as N
from myinterpreter import Interpreter, MojoCoroutine

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


def test_call_does_not_run_body():
    interp = _run(
        "ran = False\n"
        "async def coro():\n"
        "    global ran\n"
        "    ran = True\n"
        "    return 1\n"
    )
    coro_fn = interp.scope.get('coro')
    c = coro_fn(interp)
    check("async_call_returns_without_running_body", interp.scope.get('ran') is False)
    check("async_call_returns_coroutine_object", isinstance(c, MojoCoroutine))
    result = asyncio.run(c)
    check("driving_it_runs_body_and_returns_value", result == 1 and interp.scope.get('ran') is True,
          (result, interp.scope.get('ran')))


def test_await_mojo_coroutine_chain():
    interp = _run(
        "async def inner():\n"
        "    return 5\n"
        "async def outer():\n"
        "    x = await inner()\n"
        "    y = await inner()\n"
        "    return x + y\n"
    )
    outer = interp.scope.get('outer')
    result = asyncio.run(outer(interp))
    check("chained_mojo_await_mojo", result == 10, result)


def test_real_asyncio_sleep_interop():
    """The core proof-of-concept: asyncio.run() (real event loop) driving a
    Mojo async function that internally does `await asyncio.sleep(...)`,
    with genuine wall-clock timing (not a synchronous fake)."""
    interp = _run(
        "import asyncio\n"
        "async def waits(delay):\n"
        "    await asyncio.sleep(delay)\n"
        "    return 'slept'\n"
    )
    waits = interp.scope.get('waits')
    t0 = time.monotonic()
    result = asyncio.run(waits(interp, 0.08))
    dt = time.monotonic() - t0
    check("real_asyncio_run_returns_correct_value", result == 'slept', result)
    check("real_asyncio_sleep_actually_took_time", dt >= 0.06, dt)


def test_gather_real_concurrency():
    """asyncio.gather() over several Mojo coroutines must actually
    interleave via the real event loop -- three 0.1s sleeps running
    concurrently should take ~0.1s total, not ~0.3s."""
    interp = _run(
        "import asyncio\n"
        "async def worker(label, delay):\n"
        "    await asyncio.sleep(delay)\n"
        "    return label\n"
        "async def main_gather():\n"
        "    return await asyncio.gather(worker('a', 0.1), worker('b', 0.1), worker('c', 0.1))\n"
    )
    main_gather = interp.scope.get('main_gather')
    t0 = time.monotonic()
    result = asyncio.run(main_gather(interp))
    dt = time.monotonic() - t0
    check("gather_returns_all_results_in_order", result == ['a', 'b', 'c'], result)
    check("gather_ran_concurrently_not_sequentially", dt < 0.25, dt)


def test_exception_propagates_through_await():
    interp = _run(
        "import asyncio\n"
        "async def raiser():\n"
        "    await asyncio.sleep(0.01)\n"
        "    raise ValueError('boom')\n"
        "async def main_e():\n"
        "    try:\n"
        "        await raiser()\n"
        "        return 'no exception'\n"
        "    except ValueError as e:\n"
        "        return 'caught: ' + str(e)\n"
    )
    main_e = interp.scope.get('main_e')
    result = asyncio.run(main_e(interp))
    check("exception_from_awaited_real_asyncio_chain_caught", result == 'caught: boom', result)


def test_exception_raised_uncaught_from_await():
    interp = _run(
        "import asyncio\n"
        "async def raiser():\n"
        "    await asyncio.sleep(0.01)\n"
        "    raise ValueError('uncaught boom')\n"
    )
    raiser = interp.scope.get('raiser')
    try:
        asyncio.run(raiser(interp))
        check("uncaught_exception_propagates_to_real_asyncio_run", False, "did not raise")
    except ValueError as e:
        check("uncaught_exception_propagates_to_real_asyncio_run", str(e) == 'uncaught boom', str(e))


def test_concurrent_scope_isolation():
    """The highest-risk correctness area: several Mojo coroutines, each
    with LOCAL variables of the same name, driven concurrently by the real
    asyncio event loop via asyncio.gather -- each must see only its own
    locals across every await-suspend/resume, never another coroutine's.
    """
    interp = _run(
        "import asyncio\n"
        "async def accumulate(label, n, delay):\n"
        "    total = 0\n"
        "    i = 0\n"
        "    while i < n:\n"
        "        await asyncio.sleep(delay)\n"
        "        total = total + i + len(label)\n"
        "        i = i + 1\n"
        "    return (label, total)\n"
        "async def main_iso():\n"
        "    return await asyncio.gather(\n"
        "        accumulate('a', 6, 0.005),\n"
        "        accumulate('bb', 6, 0.004),\n"
        "        accumulate('ccc', 6, 0.006),\n"
        "        accumulate('dddd', 6, 0.003),\n"
        "    )\n"
    )
    main_iso = interp.scope.get('main_iso')
    result = asyncio.run(main_iso(interp))
    expected = [
        ('a', sum(range(6)) + 6 * 1),
        ('bb', sum(range(6)) + 6 * 2),
        ('ccc', sum(range(6)) + 6 * 3),
        ('dddd', sum(range(6)) + 6 * 4),
    ]
    check("concurrent_coroutines_kept_separate_scope", result == expected, result)


def test_gather_from_real_python_side_too():
    """Confirms the awaitability isn't a one-off: a MojoCoroutine mixed
    into a gather() alongside a genuine native coroutine, all driven from
    ordinary real Python async code (not just from another Mojo body)."""
    interp = _run(
        "import asyncio\n"
        "async def mojo_side(delay):\n"
        "    await asyncio.sleep(delay)\n"
        "    return 'mojo'\n"
    )
    mojo_side = interp.scope.get('mojo_side')

    async def native_side(delay):
        await asyncio.sleep(delay)
        return 'native'

    async def driver():
        return await asyncio.gather(mojo_side(interp, 0.02), native_side(0.02))

    result = asyncio.run(driver())
    check("mojo_and_native_coroutines_gather_together", result == ['mojo', 'native'], result)


def run_tests():
    for fn in [
        test_call_does_not_run_body,
        test_await_mojo_coroutine_chain,
        test_real_asyncio_sleep_interop,
        test_gather_real_concurrency,
        test_exception_propagates_through_await,
        test_exception_raised_uncaught_from_await,
        test_concurrent_scope_isolation,
        test_gather_from_real_python_side_too,
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
