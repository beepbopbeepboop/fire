def make_adder(n: int):
    def add(x: int) -> int:
        return x + n

    return add


def main():
    add3 = make_adder(3)
    add_neg = make_adder(-1)
    add0 = make_adder(0)
    print(add3(0))
    print(add3(10))
    print(add_neg(0))
    print(add_neg(-5))
    print(add0(7))
    print(add3(add_neg(4)))
    results = [make_adder(i)(i) for i in range(4)]
    print(results)
    print(add3(add3(add3(0))))


main()
