def main():
    dd = {"a": {"n": 1}}
    dl = {"a": [1, 2]}
    ds = {"a": {3}}
    print(dd.get("zz"))
    print(dd.get("a"))
    z = dd.get("zz")
    print(z is None)
    print(z)
    print(len(dd.get("a")))
    print(dd.get("a")["n"])
    w = dl.get("zz")
    print(w is None)
    print(w)
    print(dl.get("a"))
    print(len(dl.get("a")))
    s = ds.get("zz")
    print(s is None)
    print(s)
    print(ds.get("a"))


main()
