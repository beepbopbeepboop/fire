def sum_until_sentinel(values: list, sentinel: object):
    total = 0
    i = 0
    while i < len(values):
        v = values[i]
        i += 1
        if v == sentinel:
            break
        if v is None or v == "":
            continue
        total += v
    return total, i


def main():
    print(sum_until_sentinel([1, 2, 3, -1, 100], -1))
    print(sum_until_sentinel([1, None, "", 4], "x"))
    print(sum_until_sentinel([], 0))
    print(sum_until_sentinel([0, 0, 5], 5))
    print(sum_until_sentinel([2, 2], 2))
    print(sum_until_sentinel([-4, 0.5, None], None))
    print(sum_until_sentinel(["a", 1], "a"))


main()
