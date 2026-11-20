def main():
    print(repr("plain"))
    print(repr(""))
    print(repr("it's"))
    print(repr('say "hi"'))
    print(repr("both ' and \""))
    print(repr("tab\there"))
    print(repr("new\nline"))
    print(repr("back\\slash"))
    print(str("it's"))
    print(repr(" "))
    print(repr("\x00"))
    print(repr(["a'b", 'c"d']))
    print(repr(("q",)))
    print(str(["x\ty"]))


main()
