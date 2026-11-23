"""A list literal at a call-argument position inside a generator body: `_cpp_list_literal_arg_expr`
(a typed literal becomes a MojoList built by a call-once lambda, not a braced-init list).
"""


def joined(n: int):
    for i in range(n):
        yield "-".join(["a", "b", "c"])
        yield ",".join(["x", "y"])


def main():
    for s in joined(2):
        print(s)


main()
