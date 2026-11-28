def main():
    d = {"a": b"xy", "b": b"", "c": None}
    print(d.get("a"))
    print(d.get("b"))
    print(d.get("zz"))
    x = d.get("zz")
    print(x is None)
    print(d.get("a") is None)
    print(len(d.get("a")))
    print(len(d.get("b")))
    print(d.get("a") == b"xy")
    print(d.get("a") == b"zz")
    print(d.get("zz") == None)
    print(d["a"])
    print(d.get(b"a"))
    e = {"k": b"q"}
    print(e.get("k", b"dflt"))
    print(e.get("nope", b"dflt"))
    f = {b"bk": b"bv"}
    print(f.get(b"bk"))
    print(f.get(b"nope"))
    print(f[b"bk"])
    print(e["k"])
    print(e.get("k")[0:1])


main()
