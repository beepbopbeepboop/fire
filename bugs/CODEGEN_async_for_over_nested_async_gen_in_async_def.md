# CODEGEN: `async for` over a nested async generator inside an `async def` run by `asyncio.run` fails at runtime

Status: OPEN. Filed 2026-11-12 on master. Measured with `fire.py build` on master.

## Repro

    import asyncio

    async def main():
        async def gen():
            yield 11
        async for x in gen():
            print(x)

    asyncio.run(main())

CPython prints `11`.

Master builds this (rc=0) and the program fails at runtime:

    Unhandled exception: a coroutine was expected
    (exit 1)

## Related shape that does not build

    import asyncio

    async def main():
        n = 1
        async def a():
            return n + 1
        async def b():
            return n + 2
        print(await a(), await b())

    asyncio.run(main())

CPython prints `2 3`. Master refuses the build (rc=1):

    RuntimeError: cannot compile module: function(s) main (async function(s), declared `async def`) — this codegen
    compiles every function into a single straight-line C function and has no suspend/resume state-machine transform
    for generators, nor an event loop / ...

## What is NOT the bug

`test_coro_nested_async_capture.py::test_nested_async_generator_driven_by_async_for` passes on master (14 of 14 in that
file). Its shape is an ordinary `def outer()` with a nested async generator, which the coro path already handles. The
shape above is different: the `async for` sits inside an `async def` that is driven by `asyncio.run`.

## Where the history is

The captured-parameter capture crash's item 3 (the ordinary-function shape) was fixed on the
archive by `c136822d3`, whose `emit_loops.py` and `coro.py` changes are already on master. The `async def`-driven shape
was not covered by that fix. The archive branch carries no further work for it.

## Next step

Find the code path master takes for an `async for` whose body is an `async def`, under `asyncio.run`. Compare it with the
path the ordinary-function test takes. Start from the `runtime error` at the generator's first resume: "a coroutine was
expected" is raised where a value is expected to be a coroutine object, which points at how the generator handle is
passed into the `async def` body.
