def main():
    print("{} {}".format("a", "b"))
    print("{0} {1} {0}".format("x", "y"))
    print("{1}-{0}".format(1, 2))
    print("{}".format(None))
    print("{}".format(True))
    print("{}".format([1, 2]))
    print("{0:>4}|{1:<4}|".format(7, "ab"))
    print("{0:.2f}".format(3.14159))
    print("{0:03d}".format(9))
    print("{0!r}".format("q"))
    print("{}".format(""))
    print("[{:^7}]".format("mid"))
    print("{{literal}} {}".format(1))
    print("{:d} items".format(0))
    print("{} {} {}".format(-1, 0.5, "z"))


main()
