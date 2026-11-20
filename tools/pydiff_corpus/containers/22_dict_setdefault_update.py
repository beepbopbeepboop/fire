def main():
    d = {"a": 1}
    print(d.setdefault("a", 99))
    print(d.setdefault("b", 2))
    print(d)
    print(d.setdefault("c", []))
    d["c"].append(5)
    print(d["c"])
    print(d.setdefault("c", []))
    d.update({"a": 0, "e": ""})
    print(d)
    d.update([("f", None)])
    print(len(d))
    d.update(g=7)
    print(d["g"])
    other = {"a": "replaced"}
    merged = {}
    merged.update(d)
    merged.update(other)
    print(merged["a"])
    print(d["a"])
    print(sorted(merged.keys()))
    print(d.setdefault("e") == "")


main()
