def summarize(items: list) -> str:
    if not items:
        return "empty"
    total = 0
    for x in items:
        total += x
    return "n=" + str(len(items)) + " total=" + str(total)


def largest(items):
    if len(items) == 0:
        return None
    best = items[0]
    for x in items:
        if x > best:
            best = x
    return best


def main():
    print(summarize([]))
    print(summarize([4]))
    print(summarize([1, 2, 3]))
    print(summarize([-5, 5]))
    print(largest([]))
    print(largest([3, 9, 2]))
    print(largest([-1, -7]))
    print(largest([0]))


main()
