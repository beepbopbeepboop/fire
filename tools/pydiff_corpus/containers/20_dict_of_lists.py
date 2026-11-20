def group(pairs: list) -> dict:
    groups = {}
    for key, value in pairs:
        if key not in groups:
            groups[key] = []
        groups[key].append(value)
    return groups


def main():
    pairs = [("a", 1), ("b", 0), ("a", -1), ("c", ""), ("b", None), ("a", 0)]
    groups = group(pairs)
    print(groups)
    print(groups["a"])
    print(len(groups["b"]))
    print(groups["c"][0] == "")
    groups["d"] = []
    print(groups["d"])
    groups["d"].append("new")
    print(groups["d"])
    print(sorted(groups.keys()))
    print(sum(len(v) for v in groups.values()))
    print(groups.get("zz", []))
    groups["a"].extend([7, 8])
    print(groups["a"])
    print(groups["a"][-1])


main()
