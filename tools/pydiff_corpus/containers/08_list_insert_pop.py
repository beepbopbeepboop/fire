def main():
    q = ["b", "c"]
    q.insert(0, "a")
    print(q)
    q.insert(len(q), "d")
    print(q)
    q.insert(100, "e")
    print(q)
    q.insert(-1, "x")
    print(q)
    print(q.pop())
    print(q.pop(0))
    print(q.pop(-2))
    print(q)
    nums = [5, 6, 7]
    print(nums.pop(1))
    print(nums)
    print(nums.pop())
    print(nums.pop())
    print(nums)
    print(len(nums))
    empty_check = []
    print(empty_check == [])


main()
