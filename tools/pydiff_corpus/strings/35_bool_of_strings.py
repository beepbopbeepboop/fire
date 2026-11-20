def truthy(s: str) -> bool:
    if s:
        return True
    return False


def main():
    print(bool(""))
    print(bool("0"))
    print(bool(" "))
    print(bool("false"))
    print(bool("a"))
    print(bool("0.0"))
    print(truthy(""))
    print(truthy("0"))
    print(truthy(" "))
    print(not "")
    print("" or "default")
    print("x" and "y")
    print("" and "y")
    print(bool(None))
    print(bool([""]))
    print(bool(0.0))
    print("0" == 0)
    print(len(" ") == 1)


main()
