def pick(text: str, start: int, stop: int) -> str:
    return text[start:stop]


def main():
    s = "abcdefgh"
    print(s[0])
    print(s[-1])
    print(s[2:5])
    print(s[:3])
    print(s[5:])
    print(s[-3:])
    print(s[:-3])
    print(s[::2])
    print(s[::-1])
    print(s[1:6:2])
    print(s[100:])
    print(s[5:2] == "")
    print(s[-100:2])
    print(repr(s[3:3]))
    print(s[::-2])
    print(len(s[::3]))
    print(pick("hello", -2, 10))
    print("xyz"[1:-1])


main()
