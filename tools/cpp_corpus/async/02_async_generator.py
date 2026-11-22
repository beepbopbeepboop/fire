"""`async def` with a `yield`: `_gen_cpp_async_generator_unit` and
`_cpp_async_for_stmt` (the `async for` consumption loop).
"""


async def ticks(n: int):
    for i in range(n):
        yield i


async def main() -> int:
    total = 0
    async for t in ticks(3):
        total += t
    print(total)
    return 0


main()
