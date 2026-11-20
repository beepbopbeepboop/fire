def main():
    d = {"x": 1, "y": 0, "z": ""}
    del d["y"]
    print(d)
    print(d.pop("x"))
    print(d)
    print(d.pop("nope", "default"))
    print(d.pop("z"))
    print(d)
    print(len(d))
    d[1] = "one"
    d[0] = 0
    print(d.pop(0))
    print(d)
    d.clear()
    print(d)
    print(len(d))
    e = {"k": [1, 2]}
    removed = e.pop("k")
    print(removed)
    print(e)


main()
