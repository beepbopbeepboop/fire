def main():
    xs = []
    xs.append(1)
    xs.append("two")
    xs.append(0)
    print(xs)
    xs.extend([3, ""])
    print(xs)
    xs.extend("ab")
    print(xs)
    xs.append([4, 5])
    print(len(xs))
    print(xs[-1])
    xs.extend([])
    print(len(xs))
    ys = [9]
    ys.extend(ys)
    print(ys)
    zs = []
    zs.append(zs)
    print(len(zs))
    nums = [1, 2]
    nums += [3]
    print(nums)
    nums.append([])
    print(nums)


main()
