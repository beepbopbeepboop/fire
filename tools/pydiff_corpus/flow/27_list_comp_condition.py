def main():
    nums = [-2, -1, 0, 1, 2, 3, 4]
    print([n for n in nums if n])
    print([n for n in nums if not n])
    print([n * n for n in nums if n > 0])
    print([n if n >= 0 else -n for n in nums])
    print([n for n in nums if n % 2 == 0 and n != 0])
    mixed = [0, "", None, [], "x", 5, False, [0]]
    print([m for m in mixed if m])
    print([m for m in mixed if m is None])
    print(len([m for m in mixed if m == 0]))
    words = ["apple", "", "kiwi", "fig"]
    print([w.upper() for w in words if len(w) > 3])
    print([w for w in words if w or w == ""])
    print([i for i, w in enumerate(words) if not w])
    print([n for n in range(10) if n % 3 == 0][::-1])


main()
