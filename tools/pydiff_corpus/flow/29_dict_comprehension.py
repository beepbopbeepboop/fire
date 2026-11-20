def invert(d: dict) -> dict:
    return {v: k for k, v in d.items()}


def main():
    squares = {n: n * n for n in range(5)}
    print(squares)
    print(squares[4], squares.get(9, "none"))
    print({k: v for k, v in squares.items() if v % 2})
    words = ["apple", "fig", "fig", "kiwi"]
    counts = {w: len(w) for w in words}
    print(counts)
    print(len({w for w in words}))
    print(invert({"a": 1, "b": 2}))
    print({0: "zero", "": "empty", None: "none"}[""])
    print({c: i for i, c in enumerate("abc")})
    print({k: (v or "unset") for k, v in {"x": 0, "y": "", "z": 3}.items()})
    print(dict([(1, "one")]) == {1: "one"})
    print({True: "t"}[1])


main()
