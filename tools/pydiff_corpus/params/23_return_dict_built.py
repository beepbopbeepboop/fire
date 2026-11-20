def letter_counts(text):
    counts = {}
    for ch in text:
        if ch in counts:
            counts[ch] = counts[ch] + 1
        else:
            counts[ch] = 1
    return counts


def invert(d):
    out = {}
    for k in sorted(d.keys()):
        out[d[k]] = k
    return out


def main():
    c = letter_counts("banana")
    print(c["a"], c["b"], c["n"])
    print(len(letter_counts("")))
    print(letter_counts("") == {})
    print(c.get("z", 0))
    inv = invert({"x": 1, "y": 2, "w": 1})
    print(inv[1])
    print(inv[2])
    print(sorted(inv.keys()))
    print(len(invert({})))
    print(letter_counts("aA")["A"])


main()
