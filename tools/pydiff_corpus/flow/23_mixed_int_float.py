def average(values: list) -> float:
    return sum(values) / len(values)


def main():
    print(1 + 2.0)
    print(3 * 1.5)
    print(7 // 2.0)
    print(7 % 2.5)
    print(2 ** 0.5 > 1.41)
    print(4 / 2)
    print(type(4 / 2) == float)
    print(int(7.9), int(-7.9))
    print(float(3) == 3)
    print(average([1, 2, 3, 4]))
    print(average([2.5, 0]))
    print(1 == 1.0, 1 < 1.5, 2 > 1.9999)
    print(10 / 4 * 2)
    print(-7.5 // 2, -7.5 % 2)
    print(int(True) + 1.0)
    print(max(1, 2.5), min(1, 1.0))


main()
