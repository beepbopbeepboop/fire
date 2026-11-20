def main():
    scores = {"ann": 3, "bo": 0, "cy": 7}
    print(list(scores.keys()))
    print(list(scores.values()))
    print(list(scores.items()))
    for name in scores:
        print("key", name)
    for name, pts in scores.items():
        print(name, pts)
    total = 0
    for pts in scores.values():
        total += pts
    print("total", total)
    print(len(scores.keys()), len(scores.values()), len(scores.items()))
    print(("bo", 0) in scores.items())
    print("cy" in scores.keys())
    print(7 in scores.values())
    print(0 in scores.values())
    best = max(scores.items(), key=lambda kv: kv[1])
    print(best)
    print(sorted(scores.items(), key=lambda kv: kv[1]))
    empty = {}
    print(list(empty.items()))


main()
