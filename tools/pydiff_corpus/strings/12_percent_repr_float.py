def main():
    print("%r" % "hi")
    print("%r" % 'it\'s')
    print("%r" % 3)
    print("%r" % None)
    print("%r" % [1, "a"])
    print("%5.2f|" % 3.14159)
    print("%.3f" % 2.0)
    print("%8.3f|" % -1.5)
    print("%-8.1f|" % 2.25)
    print("%.0f" % 0.5)
    print("%e" % 12345.678)
    print("%g" % 0.0001)
    print("%g" % 1000000.0)
    print("%x %o" % (255, 8))
    print("%c%c" % (72, "i"))


main()
