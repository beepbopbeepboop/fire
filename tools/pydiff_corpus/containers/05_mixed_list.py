def describe(item) -> str:
    if isinstance(item, int):
        return "int:" + str(item)
    if isinstance(item, str):
        return "str:" + item
    return "other"


def main():
    mixed = [1, "one", 0, "", -5, "zero"]
    for item in mixed:
        print(describe(item))
    print(len(mixed))
    print(mixed.count(0))
    print(mixed.count(""))
    print(mixed.index("zero"))
    print(1 in mixed)
    print(True in mixed)
    print("1" in mixed)
    ints = [x for x in mixed if isinstance(x, int)]
    strs = [x for x in mixed if isinstance(x, str)]
    print(ints)
    print(strs)
    print(str(mixed[2]) + "|" + str(mixed[3]) + "|")


main()
