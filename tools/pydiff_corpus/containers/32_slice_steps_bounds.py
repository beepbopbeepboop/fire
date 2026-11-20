def main():
    s = "abcdefgh"
    print(s[::2])
    print(s[1::2])
    print(s[::-2])
    print(s[-3::-1])
    print(s[100:])
    print(s[:-100])
    print(s[2:2:1])
    print(s[::3][-1])
    nums = list(range(10))
    print(nums[7:3:-1])
    print(nums[::-3])
    print(nums[-5:-2])
    print(nums[1:9:4])
    print(nums[::100])
    print(nums[-20:20:5])
    print(nums[3:1])
    print(nums[:0] == [])


main()
