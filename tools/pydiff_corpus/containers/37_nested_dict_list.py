def build(entries: list) -> dict:
    tree = {}
    for entry in entries:
        dept, person = entry
        tree.setdefault(dept, {})
        tree[dept][person] = len(person)
    return tree


def main():
    staff = [("eng", "ann"), ("eng", "bo"), ("ops", ""), ("ops", "cy")]
    tree = build(staff)
    print(tree)
    print(tree["eng"]["bo"])
    print(tree["ops"][""])
    print(len(tree["ops"]))
    print(sorted(tree["eng"].items()))
    print("cy" in tree["ops"])
    print("ann" in tree)
    matrix = {"row": [[0, 1], [2, ""]]}
    print(matrix["row"][1][1])
    print(matrix["row"][0][-1])
    matrix["row"][0].append(None)
    print(matrix)
    print(len(matrix["row"]), len(matrix["row"][0]))


main()
