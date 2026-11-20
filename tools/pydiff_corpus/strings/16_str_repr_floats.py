def main():
    values = [1.0, 0.5, 1e10, -0.0, 1e16, 1.5e-5, 100.0, 0.1, 2.0 / 3.0]
    for v in values:
        print(str(v))
        print(repr(v))
    print(str(1e22))
    print(str(float("inf")))
    print(str(-float("inf")))
    print(str(float(3)))
    print(str(10 / 2))
    print(repr(float("nan") != float("nan")))
    print(str(1e-4))
    print(str(123456789.0))


main()
