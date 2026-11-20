def parse(text: str):
    if text == "":
        return None
    if text.isdigit():
        return int(text)
    if text == "-":
        return 0.5
    return text


def type_name(v):
    if v is None:
        return "NoneType"
    return type(v).__name__


def main():
    inputs = ["12", "", "abc", "-", "0", "007"]
    for s in inputs:
        v = parse(s)
        print(repr(v), type_name(v))
    print(parse("42") + 1)
    print(parse("x") + "y")
    print(parse("") is None)
    print(parse("0") == 0)
    print(parse("-") == 0.5)
    print(type_name(parse("9") * 2))


main()
