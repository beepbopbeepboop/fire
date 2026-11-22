"""`try`/`except`/`raise` confined to the coroutine's own translation unit:
`_cpp_try_stmt` and `_cpp_raise_stmt`, and the exception-state plumbing they
emit at the `_resume` boundary.
"""


def safe_div(xs):
    for x in xs:
        try:
            if x == 0:
                raise ValueError("division by zero")
            yield 120 // x
        except ValueError as exc:
            yield -1


def main():
    total = 0
    for v in safe_div([2, 0, 5]):
        total += v
    print(total)


main()
