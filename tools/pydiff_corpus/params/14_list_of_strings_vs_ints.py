def join_all(parts):
    out = ""
    for p in parts:
        out = out + p
    return out


def add_all(nums):
    total = 0
    for n in nums:
        total = total + n
    return total


def count_items(items):
    return len(items)


def main():
    print(join_all(["a", "b", "c"]))
    print(join_all([]))
    print(join_all([""]))
    print(add_all([1, 2, 3]))
    print(add_all([]))
    print(add_all([-4, 4]))
    print(count_items(["x", "y"]))
    print(count_items([1, "1", 1.0]))
    print(join_all(["10", "20"]))
    print(add_all([10, 20]))
    print(count_items([[], [1]]))


main()
