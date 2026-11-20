def first_negative(nums: list) -> int:
    for i, n in enumerate(nums):
        if n < 0:
            return i
    return -1


def first_repeat(words: list):
    seen = []
    for w in words:
        if w in seen:
            return w
        seen.append(w)
    return None


def contains_zero(values: list) -> bool:
    for v in values:
        if v == 0:
            return True
    return False


def main():
    print(first_negative([3, 4, -1, -2]))
    print(first_negative([1, 2]))
    print(first_negative([]))
    print(first_repeat(["a", "b", "a"]))
    print(first_repeat(["x", "y"]))
    print(first_repeat([]))
    print(contains_zero([1, 0.0, 2]))
    print(contains_zero([False, ""]))
    print(contains_zero([]))
    print(contains_zero([None, 1]))


main()
