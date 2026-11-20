def floor_div(a: int, b: int) -> int:
    return a // b


def mod(a: int, b: int) -> int:
    return a % b


def trunc_div(a: int, b: int) -> int:
    return int(a / b)


def main():
    print(floor_div(-7, 2))
    print(floor_div(7, -2))
    print(floor_div(-7, -2))
    print(mod(-7, 3))
    print(mod(7, -3))
    print(mod(-6, 3))
    print(trunc_div(-7, 2))
    print(trunc_div(7, -2))
    print(abs(-0))
    print(divmod(-7, 2))
    print(-7 // 2 == floor_div(-7, 2))
    print(-7 % 2)
    print((-7) % 2 == mod(-7, 2))


main()
