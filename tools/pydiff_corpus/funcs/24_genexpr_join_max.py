def main():
    words = ["a", "bb", "ccc"]
    print(",".join(w.upper() for w in words))
    print("".join(c for c in "h-e-l" if c != "-"))
    print("".join(str(n) for n in range(4)))
    print(repr("".join(c for c in "")))
    print(max(len(w) for w in words))
    print(max((w for w in []), default="none"))
    print(max(x * x for x in [-5, 3, 4]))
    print(min(abs(x) for x in [-5, 3, 4]))
    print("|".join(w for w in words if len(w) > 1))
    print(" ".join(str(x) for x in [None, False, 0.5]))
    print(len(",".join(w for w in [])))


main()
