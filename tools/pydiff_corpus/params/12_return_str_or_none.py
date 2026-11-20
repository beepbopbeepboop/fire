def first_word(text):
    parts = text.split()
    if len(parts) == 0:
        return None
    return parts[0]


def last_char(text: str):
    if text == "":
        return None
    return text[-1]


def main():
    print(first_word("hello there"))
    print(first_word("   "))
    print(first_word(""))
    print(first_word("  one"))
    print(last_char("abc"))
    print(last_char(""))
    print(last_char("x"))
    w = first_word("")
    print(w is None)
    print(w or "default")
    print(first_word("a b") or "default")


main()
