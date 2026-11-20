def total_len(xs: list) -> int:
    n = 0
    for x in xs:
        n += len(x)
    return n


def main():
    names = ["bob", "al", "", "carol"]
    nums = [3, 0, -12, 40]
    print(len(names))
    print(len(nums))
    print(total_len(names))
    print(sorted(names))
    print(sorted(nums))
    print(max(nums), min(nums))
    print(max(names), repr(min(names)))
    print("" in names)
    print(0 in nums)
    print("0" in nums)
    print(names[2] == "")
    print(nums[1] == False)
    print(sorted(nums, reverse=True))


main()
