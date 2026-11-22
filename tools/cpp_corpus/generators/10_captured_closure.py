"""A closure capture read by a generator: `_cpp_captured_names` /
`_enclosing_scope_with_locals` in `cpp_async`, and the captured-name
`IdentExpr` arm (a by-reference capture dereferences its pointer).
"""


def make_adder(step: int):
    def add(n: int):
        for i in range(n):
            yield i + step
    return add


def main():
    add = make_adder(100)
    total = 0
    for v in add(3):
        total += v
    print(total)


main()
