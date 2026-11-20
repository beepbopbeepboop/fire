def show_labels(table):
    keys = sorted(table.keys())
    for k in keys:
        print(k, "->", table[k])
    return len(keys)


def sum_counts(table):
    total = 0
    for k in sorted(table.keys()):
        total = total + table[k]
    return total


def main():
    names = {"b": "bee", "a": "ay"}
    counts = {"x": 3, "y": -1, "z": 0}
    print(show_labels(names))
    print(sum_counts(counts))
    print(show_labels({}))
    print(sum_counts({}))
    print(show_labels({"k": ""}))
    print(sum_counts({"only": 7}))
    print(names.get("missing", "none"))
    print(counts.get("missing", -100))
    print(counts.get("z", -100))
    print(len(names) + len(counts))


main()
