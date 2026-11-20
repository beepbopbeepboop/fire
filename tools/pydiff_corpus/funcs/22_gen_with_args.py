def take_every(items, step):
    for i in range(0, len(items), step):
        yield items[i]


def repeat_text(s, times):
    for _ in range(times):
        yield s


def windows(seq, size):
    for i in range(len(seq) - size + 1):
        yield seq[i:i + size]


def main():
    print(list(take_every([1, 2, 3, 4, 5], 2)))
    print(list(take_every([], 3)))
    print(list(take_every(["a", "b"], 1)))
    print(list(repeat_text("ab", 0)))
    print(list(repeat_text("", 3)))
    print(list(repeat_text("x", 2)))
    print(list(windows([1, 2, 3, 4], 2)))
    print(list(windows([1, 2], 5)))
    print(list(windows("hello", 3)))
    print("".join(repeat_text("-", 4)))


main()
