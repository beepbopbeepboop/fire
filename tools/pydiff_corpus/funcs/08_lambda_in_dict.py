def main():
    table = {
        "inc": lambda x: x + 1,
        "dbl": lambda x: x * 2,
        "str": lambda x: str(x),
        "neg": lambda x: -x,
        "is_empty": lambda x: len(x) == 0,
    }
    print(table["inc"](4))
    print(table["dbl"](-3))
    print(table["str"](-7))
    print(table["neg"](0))
    print(table["is_empty"](""))
    print(table["is_empty"]([0]))
    for key in sorted(table):
        print(key, table[key](1) if key != "is_empty" else table[key]([]))
    print("dbl" in table, "sqrt" in table)
    print(table.get("missing", lambda x: "none")(9))
    print(len(table))


main()
