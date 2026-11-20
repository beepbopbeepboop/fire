def main():
    nums = [3, -1, 0, 10, -7, 2, 2]
    print(sorted(nums))
    print(sorted(nums, key=lambda x: abs(x)))
    print(sorted(nums, key=lambda x: -x))
    print(sorted(nums, key=lambda x: x % 3))
    copy = nums[:]
    copy.sort(key=lambda x: x % 3)
    print(copy)
    print(nums)
    print(sorted([], key=lambda x: x))
    print(sorted([5], key=lambda x: -x))
    print(sorted(nums, key=lambda x: (x < 0, x)))
    print(sorted(nums, key=lambda x: abs(x), reverse=True))


main()
