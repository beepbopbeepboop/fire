def pick_slot(n: int) -> int:
    return n % 3


def last_index(items):
    return len(items) - 1


def middle(items):
    return len(items) // 2


def main():
    letters = ["a", "b", "c"]
    print(letters[pick_slot(0)])
    print(letters[pick_slot(4)])
    print(letters[pick_slot(-1)])
    print(letters[last_index(letters)])
    print(letters[middle(letters)])
    print(letters[middle(["x", "y"])])
    print(letters[-1])
    nums = [10, 20, 30, 40]
    print(nums[middle(nums)])
    print(nums[pick_slot(5)] + nums[last_index(nums)])
    print(nums[last_index([0])])


main()
