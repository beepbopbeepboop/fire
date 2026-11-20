def lookup(d: dict, key, default):
    return d.get(key, default)


def main():
    d = {"zero": 0, "empty": "", "none": None, "t": True}
    print(d.get("zero"))
    print(d.get("zero", 5))
    print(d.get("empty", "fallback"))
    print(d.get("none", "fallback"))
    print(d.get("none"))
    print(d.get("absent"))
    print(d.get("absent", 0))
    print(lookup(d, "zero", 7))
    print(lookup(d, "nope", 7))
    print(lookup(d, "t", False))
    print(d.get("t", False) or "was falsy")
    value = d.get("zero") or "replaced"
    print(value)
    value2 = d.get("zero", "kept")
    print(value2)
    print(d.get("empty") == "")


main()
