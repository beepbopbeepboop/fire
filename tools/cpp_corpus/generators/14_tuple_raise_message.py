"""A `raise` whose message is a tuple literal inside a generator body: `_cpp_raise_tuple_msg_expr` builds
the `char *` repr of the tuple as a call-once lambda.
"""


def checked(n: int):
    for i in range(n):
        if i == 2:
            raise ValueError((1, "two", i))
        yield i


def main():
    try:
        for v in checked(4):
            print(v)
    except ValueError as e:
        print("caught")


main()
