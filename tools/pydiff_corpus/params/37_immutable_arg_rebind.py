def bump(n):
    n = n + 1
    return n


def rename(s):
    s = s + "!"
    return s


def set_flag(flag):
    flag = not flag
    return flag


def main():
    x = 10
    y = bump(x)
    print(x, y)
    print(bump(-1))
    s = "hi"
    t = rename(s)
    print(s, t)
    print(rename(""))
    f = True
    g = set_flag(f)
    print(f, g)
    print(set_flag(set_flag(False)))
    t2 = (1, 2)
    print(t2 + (3,), t2)
    print(bump(0) == 1 and rename("") == "!")
    print(x == 10)


main()
