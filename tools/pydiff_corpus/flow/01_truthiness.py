def show(label, value):
    if value:
        print(label, "truthy")
    else:
        print(label, "falsy")


def main():
    show("zero", 0)
    show("one", 1)
    show("minus one", -1)
    show("float zero", 0.0)
    show("float tiny", 0.0001)
    show("empty str", "")
    show("str a", "a")
    show("str zero", "0")
    show("empty list", [])
    show("list zero", [0])
    show("empty dict", {})
    show("none", None)
    show("false", False)
    show("true", True)
    print("not 0 =", not 0)
    print("not []:", not [])
    print("not None:", not None)
    print("not 'x':", not "x")
    n = 3
    count = 0
    while n:
        count += 1
        n -= 1
    print("while count", count)
    print("bool(0.0)", bool(0.0))
    print("bool(' ')", bool(" "))


main()
