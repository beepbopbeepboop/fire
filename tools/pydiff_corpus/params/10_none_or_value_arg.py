def describe(item):
    if item is None:
        return "nothing"
    if item is False:
        return "false-object"
    if item == 0:
        return "zero-like"
    return "thing " + str(item)


def pick(first, second=None):
    if second is None:
        return first
    return second


def main():
    print(describe(None))
    print(describe(False))
    print(describe(0))
    print(describe(""))
    print(describe([]))
    print(describe("a"))
    print(pick(1))
    print(pick(1, None))
    print(pick(1, 0))
    print(pick(1, ""))
    print(pick(None))
    print(pick(None, 5))


main()
