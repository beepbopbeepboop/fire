def main():
    vals = [3, 0, "x", 0, "", 3, None, False]
    print(vals.count(0))
    print(vals.count(3))
    print(vals.count(False))
    print(vals.count(""))
    print(vals.index(0))
    print(vals.index("x"))
    print(vals.index(None))
    vals.remove(0)
    print(vals)
    vals.remove(3)
    print(vals)
    print(vals.count(0))
    names = ["ann", "", "bo", ""]
    names.remove("")
    print(names)
    print("" in names)
    names.remove("")
    print(names)
    print(names.count(""))
    print(len(names))


main()
