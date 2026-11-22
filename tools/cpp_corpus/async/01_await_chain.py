"""`await` on an async function: `_gen_cpp_async_unit` (its own promise type,
separate from the generator one) and `_cpp_expr`'s AwaitExpr arm.
"""


async def child(n: int) -> int:
    return n + 1


async def main() -> int:
    a = await child(1)
    b = await child(a)
    print(a + b)
    return 0


main()
