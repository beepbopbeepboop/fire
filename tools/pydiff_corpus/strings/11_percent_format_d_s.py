def line(name: str, count: int) -> str:
    return "%s has %d items" % (name, count)


def main():
    print("%d" % 42)
    print("%d" % -7)
    print("%5d|" % 42)
    print("%-5d|" % 42)
    print("%05d" % 42)
    print("%s" % "text")
    print("%s" % 3)
    print("%s" % None)
    print("%s" % True)
    print("%8s|" % "right")
    print("%-8s|" % "left")
    print(line("box", 3))
    print(line("", 0))
    print("%s and %s" % ("a", 1))
    print("%d%%" % 50)
    print("%d" % True)


main()
