"""Re-raising an exception VALUE held in a local inside a generator body: the zero-tag `throw` of
`_cpp_raise_stmt` (the value's message and object, with no exception-type tag).
"""


def gen(n: int):
    err = ValueError("bad value")
    for i in range(n):
        if i == 1:
            raise err
        yield i


def main():
    try:
        for v in gen(3):
            print(v)
    except ValueError:
        print("caught")


main()
