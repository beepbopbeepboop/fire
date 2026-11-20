def main():
    squares = {}
    for i in range(-2, 4):
        squares[i] = i * i
    print(squares)
    print(squares[-2])
    print(squares[0])
    print(squares.get(10))
    print(squares.get(-1, "none"))
    print(0 in squares)
    print(True in squares)
    print(1.0 in squares)
    squares[True] = 99
    print(squares[1])
    print(len(squares))
    keys = sorted(squares.keys())
    print(keys)
    print(sorted(squares.values()))
    print(squares[False])
    print(squares.get(2.0))


main()
