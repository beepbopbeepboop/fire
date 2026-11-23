"""String concatenation and repetition inside a generator body: `mojo_str_cat` and `mojo_cstr_repeat`
built by `_cpx_binary_op` as call shapes (a str on either side, and a word on the other).
"""


def rows(n: int):
    tag = "row"
    for i in range(n):
        yield tag + "-x"
        yield "=" * i
        yield i * "+"


def main():
    for s in rows(3):
        print(s)


main()
