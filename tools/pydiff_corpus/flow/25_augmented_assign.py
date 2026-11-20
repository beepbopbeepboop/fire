def main():
    n = 10
    n += 5
    print(n)
    n -= 20
    print(n)
    n *= -3
    print(n)
    n //= 4
    print(n)
    n %= 5
    print(n)
    n **= 3
    print(n)
    n /= 2
    print(n)
    s = "ab"
    s += "cd"
    s *= 2
    print(s)
    lst = [1]
    lst += [2, 3]
    lst *= 2
    print(lst)
    alias = lst
    alias += [9]
    print(lst is alias, lst)
    copy = lst
    copy = copy + [0]
    print(lst is copy, len(lst), len(copy))
    m = 7
    m //= -2
    print(m)
    m %= -2
    print(m)
    flag = True
    flag += 1
    print(flag)
    b = 6
    b &= 3
    b |= 8
    b ^= 1
    print(b)


main()
