def check(d: dict, key) -> str:
    if key not in d:
        return "absent"
    if d[key]:
        return "truthy"
    return "falsy"


def main():
    d = {"a": 0, "b": "", "c": [], "d": 1, "e": None, "f": False, "g": "x"}
    for k in ["a", "b", "c", "d", "e", "f", "g", "h"]:
        print(k + " " + check(d, k))
    print(d.get("a", 9))
    print(d.get("e", 9))
    print(d.get("h", 9))
    count = 0
    for k in d:
        if not d[k]:
            count += 1
    print(count)
    print(len(d))
    print(d["c"] == [])
    print(d["f"] == 0)


main()
