def for_each(items, callback):
    for x in items:
        callback(x)


def show(x):
    print("item", x)


def main():
    results = []
    for_each([1, 2, 3], lambda x: results.append(x * 10))
    print(results)
    for_each(["a", None, 0], show)
    for_each([], show)
    seen = []
    for_each([0, "", False], lambda x: seen.append(type(x).__name__))
    print(seen)
    total = [0]

    def add_to_total(x):
        total[0] += x

    for_each([5, -5, 2], add_to_total)
    print(total[0])
    for_each([[1], []], lambda lst: print("len", len(lst)))
    print(len(results))
    print(results[-1])


main()
