def split_pair(n: int) -> tuple:
    return n // 10, n % 10


def min_max(items):
    if not items:
        return None, None
    return min(items), max(items)


def swap(a, b):
    return b, a


def main():
    tens, ones = split_pair(42)
    print(tens, ones)
    tens, ones = split_pair(0)
    print(tens, ones)
    tens, ones = split_pair(-7)
    print(tens, ones)
    lo, hi = min_max([3, -2, 9])
    print(lo, hi)
    lo, hi = min_max([])
    print(lo, hi)
    pair = min_max([5])
    print(pair)
    print(len(pair))
    x, y = swap(1, "two")
    print(x, y)
    t = swap(None, 0)
    print(t)
    print(t[0] is None)


main()
