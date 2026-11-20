def main():
    power = lambda x, k=2: x ** k
    shift = lambda x, k=0: x + k
    print(power(3))
    print(power(3, 3))
    print(power(-2))
    print(power(0, 0))
    print(shift(10))
    print(shift(10, -4))
    funcs = [lambda i=i: i * 10 for i in range(3)]
    for f in funcs:
        print(f())
    scaled = [lambda x, s=s: x * s for s in (1, -1, 0)]
    print([g(5) for g in scaled])
    print(scaled[1](0), scaled[2](-99))


main()
