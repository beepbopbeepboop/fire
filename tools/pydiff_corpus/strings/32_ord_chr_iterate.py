def main():
    text = "Hi!"
    for ch in text:
        print(ch)
    for ch in "":
        print("never")
    print(ord("A"))
    print(ord("a"))
    print(ord("0"))
    print(chr(65))
    print(chr(97 + 2))
    print(chr(ord("a") + 25))
    print(ord(" "))
    print(chr(10) == "\n")
    print(list("abc"))
    print([ord(c) for c in "AB"])
    print("".join([chr(c) for c in [72, 105]]))
    print(ord("é"))
    print(len("é"))
    print(text[::-1])


main()
