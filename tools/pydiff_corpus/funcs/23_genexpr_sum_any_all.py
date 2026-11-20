def main():
    nums = [1, -2, 3, 0]
    print(sum(x * x for x in nums))
    print(any(x < 0 for x in nums))
    print(all(x < 5 for x in nums))
    print(all(x != 0 for x in nums))
    print(sum(x for x in []))
    print(all(x for x in []))
    print(any(x for x in []))
    print(sum(1 for x in nums if x))
    print(sum(x for x in nums if x > 0))
    print(any(s == "" for s in ["a", ""]))
    print(all(isinstance(x, int) for x in [1, True, 0]))
    print(sum(0.5 for _ in range(4)))


main()
