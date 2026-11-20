def classify(s: str) -> str:
    if s.isdigit():
        return "digits"
    if s.isalpha():
        return "letters"
    if s.isspace():
        return "space"
    return "other"


def main():
    print("123".isdigit())
    print("12a".isdigit())
    print("".isdigit())
    print("abc".isalpha())
    print("ab1".isalpha())
    print("".isalpha())
    print(" \t".isspace())
    print("".isspace())
    print("ABC".isupper())
    print("AbC".isupper())
    print("123".isupper())
    print("abc".islower())
    print(classify("42"))
    print(classify("hi"))
    print(classify("  "))
    print(classify(""))
    print(classify("a1"))
    print("abc123".isalnum())


main()
