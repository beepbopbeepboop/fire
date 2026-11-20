def label(value: object = None) -> str:
    if value is None:
        return "missing"
    if value == 0:
        return "zero"
    return "value=" + str(value)


def main():
    print(label())
    print(label(None))
    print(label(0))
    print(label(""))
    print(label(False))
    print(label([]))
    print(label(-1))
    print(label("text"))


main()
