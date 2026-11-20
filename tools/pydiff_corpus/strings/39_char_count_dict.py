def count_chars(text: str) -> dict:
    counts = {}
    for ch in text:
        if ch in counts:
            counts[ch] = counts[ch] + 1
        else:
            counts[ch] = 1
    return counts


def main():
    c = count_chars("banana")
    print(c)
    print(c["a"])
    print(c.get("z", 0))
    print(count_chars(""))
    print(count_chars("aA aA"))
    print(len(count_chars("hello world")))
    print(count_chars(" ")[" "])
    counts = count_chars("mississippi")
    for key in sorted(counts.keys()):
        print(key, counts[key])
    print(sorted(count_chars("cab").items()))
    print(count_chars("a\tb\\a"))


main()
