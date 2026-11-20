def main():
    square = lambda x: x * x
    neg = lambda x: -x
    is_zero = lambda x: x == 0
    concat = lambda a, b: a + b
    print(square(4))
    print(square(-3))
    print(square(0))
    print(neg(0))
    print(neg(-2))
    print(is_zero(0))
    print(is_zero(""))
    print(is_zero(False))
    print(is_zero(None))
    print(concat("ab", ""))
    print(concat([1], [None, 0]))
    print(concat(0, 0.5))
    print(square(neg(3)))


main()
