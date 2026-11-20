def has(items: list, needle) -> bool:
    return needle in items


def main():
    items = [0, "", None, False, 1, "a"]
    print(has(items, 0))
    print(has(items, ""))
    print(has(items, None))
    print(has(items, 2))
    print(has(items, "A"))
    print(has(items, 1))
    print(has(items, True))
    print(has(items, 0.0))
    print(None not in items)
    print("a" not in items)
    print(has([], 0))
    print(has([], None))
    empty: list = []
    print(has(empty, ""))
    print(len(items))


main()
