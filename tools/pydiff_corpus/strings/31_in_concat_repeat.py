def main():
    s: str = "hello"
    print("ell" in s)
    print("" in s)
    print("" in "")
    print("xyz" in s)
    print("H" in s)
    print("lo" not in s)
    print("a" in [])
    print("ab" + "cd")
    print("" + "")
    print("ab" * 3)
    print("ab" * 0)
    print("ab" * -1 == "")
    print(3 * "-")
    print(s + str(1) + repr(None))
    x = "a"
    x += "b"
    x += ""
    print(x)
    print(len(x * 4))


main()
