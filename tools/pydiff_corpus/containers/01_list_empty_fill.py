def fill(n: int) -> list:
    out = []
    i = 0
    while i < n:
        out.append(i * i)
        i += 1
    return out


def main():
    empty = []
    print(len(empty))
    squares = fill(6)
    print(squares)
    print(squares[0])
    print(squares[-1])
    print(squares[2:4])
    print(squares[-3:])
    print(squares[:2])
    print(fill(0))
    print(len(fill(0)))
    print(squares[-6])


main()
