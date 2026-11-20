def add_offset(value: int, offset: int = 10) -> int:
    return value + offset


def main():
    print(add_offset(1))
    print(add_offset(1, 2))
    print(add_offset(0))
    print(add_offset(-1))
    print(add_offset(-10, 0))
    print(add_offset(5, -5))
    print(add_offset(0, offset=0))
    print(add_offset(3, offset=-3))


main()
