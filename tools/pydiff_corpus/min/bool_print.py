def is_pos(n):
    return n > 0

def main():
    r = is_pos(3)
    print(r)
    print(is_pos(-1))
    flags = [is_pos(1), is_pos(-2)]
    print(flags)
    f = lambda n: n > 0
    print(f(5))
    print(not r)
    print(bool(""))
    print(bool("0"))
main()
