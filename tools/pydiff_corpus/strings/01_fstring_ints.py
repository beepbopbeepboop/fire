def show(n: int) -> str:
    return f"value={n}"


def main():
    values = [0, -1, 42, 1000000, -987654321]
    for v in values:
        print(f"int: {v}")
    print(f"sum: {sum(values)}")
    print(f"neg: {-5 + 2}")
    print(show(0))
    print(show(-1))
    print(f"{7 // 2} {-7 // 2} {-7 % 3}")
    print(f"{2 ** 10}")
    print(f"{True + 1}")
    print(f"{len(values) * 3}")


main()
