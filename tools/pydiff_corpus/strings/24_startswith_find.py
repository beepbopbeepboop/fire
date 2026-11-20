def main():
    s = "hello world"
    print(s.startswith("hell"))
    print(s.startswith("world"))
    print(s.endswith("world"))
    print(s.endswith(""))
    print("".startswith(""))
    print("".startswith("a"))
    print(s.find("o"))
    print(s.rfind("o"))
    print(s.find("xyz"))
    print(s.find(""))
    print(s.find("o", 5))
    print("".find("a"))
    print(s.index("wor"))
    print(s.rindex("l"))
    print(s.find("l", 3, 5))
    print(s.startswith(("x", "he")))


main()
