def vowel_count(text: str) -> int:
    return len([c for c in text if c in "aeiouAEIOU"])


def main():
    s = "Hello, World 42!"
    print([c for c in s if c.isalpha()])
    print("".join([c.lower() for c in s if c.isupper()]))
    print(vowel_count(s), vowel_count(""))
    print([c * 2 for c in "ab"])
    print("-".join([c for c in "xyz"]))
    print({c: s.count(c) for c in "lo"})
    print([ord(c) - ord("0") for c in "907" if c.isdigit()])
    print(sum(1 for c in s if c == " "))
    print([(i, c) for i, c in enumerate("hi!") if c != "!"])
    print("".join(c for c in "a1b2" if not c.isdigit()))
    print(list("") == [], list("ab"))
    print(["" if c == " " else c for c in "a b"])


main()
