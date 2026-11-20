def main():
    nums = [4, -2, 9, 0, 4]
    nums.sort()
    print(nums)
    nums.sort(reverse=True)
    print(nums)
    nums.reverse()
    print(nums)
    words = ["pear", "Apple", "fig", ""]
    print(sorted(words))
    print(sorted(words, key=len))
    print(sorted(words, key=len, reverse=True))
    print(sorted(words, key=lambda s: s.lower()))
    print(words)
    copy = sorted(nums)
    print(copy is nums)
    print(nums == copy)
    print(sorted([]))
    lst = []
    lst.sort()
    print(lst)
    lst.reverse()
    print(lst)
    print(sorted([True, False, 1, 0]))


main()
