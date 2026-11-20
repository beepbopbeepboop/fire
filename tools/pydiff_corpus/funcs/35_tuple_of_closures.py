def make_ops(base: int):
    def add(x: int) -> int:
        return base + x

    def mul(x: int) -> int:
        return base * x

    def describe() -> str:
        return "base=" + str(base)

    return add, mul, describe


def main():
    add, mul, desc = make_ops(4)
    print(add(0))
    print(add(-4))
    print(mul(3))
    print(mul(0))
    print(desc())
    add0, mul0, desc0 = make_ops(0)
    print(add0(5))
    print(mul0(5))
    print(desc0())
    print(add(mul(2)))
    ops = make_ops(-1)
    print(ops[1](-1))
    print(len(ops))
    print(ops[2]())


main()
