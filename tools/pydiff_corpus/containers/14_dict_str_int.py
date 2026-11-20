def count_words(words: list) -> dict:
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    return counts


def main():
    words = ["red", "blue", "red", "", "blue", "red", ""]
    counts = count_words(words)
    print(counts)
    print(len(counts))
    print(counts["red"])
    print(counts[""])
    print(counts.get("green", -1))
    counts["blue"] += 10
    print(counts["blue"])
    print(sum(counts.values()))
    print(max(counts.values()))
    total = 0
    for k in counts:
        total += counts[k]
    print(total)
    print("" in counts)
    print(counts["red"] == 3)
    print(counts["missing"] if "missing" in counts else "none")


main()
