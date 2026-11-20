def main():
    print(str(True))
    print(repr(False))
    print(str(None))
    print(repr(None))
    print(str(True == 1))
    print(repr(1 == 1.0))
    print(str(None == False))
    print(repr(not None))
    print(repr(bool(None)))
    print(str(True and None))
    print(str(0 or None))
    print(repr(bool([])))
    print(repr(None is None))
    print(str([True, None, False]))


main()
