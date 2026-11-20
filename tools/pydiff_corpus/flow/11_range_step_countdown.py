def countdown(start: int, stop: int, step: int) -> list:
    out = []
    for i in range(start, stop, step):
        out.append(i)
    return out


def main():
    print(list(range(10, 0, -3)))
    print(list(range(0, 10, 4)))
    print(list(range(5, 5)))
    print(list(range(-1, -10, -2)))
    print(countdown(3, -3, -1))
    print(countdown(0, 7, 2))
    print(countdown(9, 0, 1))
    print(len(range(0, 100, 7)))
    total = 0
    for k in range(20, 0, -5):
        total += k
    print("total", total)
    print(range(3, 9, 2)[1])
    print(list(range(1, 4)) * 2)
    print(sum(range(0, 11, 5)))


main()
