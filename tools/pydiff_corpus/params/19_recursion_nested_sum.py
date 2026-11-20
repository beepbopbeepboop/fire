def sum_nested(items: list) -> int:
    total = 0
    for x in items:
        if isinstance(x, list):
            total = total + sum_nested(x)
        else:
            total = total + x
    return total


def depth(items):
    best = 1
    for x in items:
        if isinstance(x, list):
            d = 1 + depth(x)
            if d > best:
                best = d
    return best


def main():
    print(sum_nested([]))
    print(sum_nested([1, 2, 3]))
    print(sum_nested([1, [2, 3], 4]))
    print(sum_nested([[], [-1], [0]]))
    print(sum_nested([[[5]], 5]))
    print(depth([]))
    print(depth([1, 2]))
    print(depth([1, [2, [3]]]))
    print(sum_nested([[10, [20]], [30, []]]))


main()
