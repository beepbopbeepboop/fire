def stats(xs: list):
    return sum(xs), min(xs), max(xs)


def main():
    nums = [4, -1, 0, 7, -1]
    print(sum(nums))
    print(min(nums))
    print(max(nums))
    print(stats(nums))
    print(sum([]))
    print(sum([], 10))
    print(sum([0.5, 1]))
    print(sum([True, True, False]))
    print(max([3, 3.0, 2]))
    print(min("hello"), max("hello"))
    print(min([2, -2], key=abs))
    print(max([], default="none"))
    print(repr(min(["", "a"])))
    print(sum(x * 2 for x in nums if x > 0))
    print(max(len(s) for s in ["", "abc", "de"]))


main()
