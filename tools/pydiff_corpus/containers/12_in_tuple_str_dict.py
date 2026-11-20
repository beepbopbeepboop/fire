def main():
    t = (0, "", None, "abc")
    d = {"k": 0, "": 1, "n": None}
    s = "hello"
    print(0 in t)
    print("" in t)
    print(None in t)
    print("ab" in t)
    print("k" in d)
    print(0 in d)
    print("" in d)
    print("n" in d)
    print(d["n"] is None)
    print("ell" in s)
    print("" in s)
    print("z" not in s)
    print(t.index(None))
    print(d.get("k") == 0)
    print(len(t) + len(d) + len(s))


main()
