def capitalize_words(sentence: str) -> str:
    return " ".join(w.capitalize() for w in sentence.split())


def word_lengths(sentence: str) -> list:
    return [len(w) for w in sentence.split()]


def main():
    s = "  the quick  brown fox  "
    print(capitalize_words(s))
    print(word_lengths(s))
    print(len(s.split()))
    print(s.strip().upper())
    print(capitalize_words(""))
    print(word_lengths(""))
    print(" ".join(s.split()[::-1]))
    print("-".join(s.split(" ")))
    print(s.strip().title().swapcase())
    print("".join(sorted(set("mississippi"))))
    print(s.strip().split(" ", 1)[1].upper().lower())


main()
