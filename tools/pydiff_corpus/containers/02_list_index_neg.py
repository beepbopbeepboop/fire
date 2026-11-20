def pick(items: list, idx: int):
    return items[idx]


def main():
    words = ["a", "bb", "", "dddd"]
    print(pick(words, 0))
    print(pick(words, -1))
    print(pick(words, 2) == "")
    print(len(pick(words, -2)))
    nums = [10, 0, -1, 7]
    print(pick(nums, 1))
    print(pick(nums, -2))
    print(pick(nums, -1) + 1)
    print(nums[-4])
    print(nums.index(-1))
    print(nums[1] or "zero-falsy")
    print(words[-1][-1])
    print(nums[0] - nums[-1])


main()
