def main():
    d = {}
    print(len(d))
    print(d)
    print(bool(d))
    print("x" in d)
    print(d.get("x"))
    print(d.get("x", "missing"))
    print(list(d.keys()))
    print(list(d.values()))
    print(list(d.items()))
    d["first"] = 1
    print(len(d))
    print(bool(d))
    print(d)
    e = dict()
    print(e == {})
    print(d == e)
    for k in d:
        print("never", k)
    print(len(e))


main()
