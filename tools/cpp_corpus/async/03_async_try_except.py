"""`try`/`except`/`raise` inside an async function: `_cpp_try_stmt` on the
async promise path, where the exception state is translated to the existing
`mojo_exc_*` globals at the `_value`/`_is_done` boundary.
"""


async def risky(v: int) -> int:
    try:
        if v < 0:
            raise ValueError("negative")
        return v * 2
    except ValueError:
        return -1


async def main() -> int:
    print(await risky(2))
    print(await risky(-1))
    return 0


main()
