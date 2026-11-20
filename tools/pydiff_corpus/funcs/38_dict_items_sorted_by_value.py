def main():
    scores = {"ann": 3, "bob": 1, "cy": 3, "dee": 0, "eve": -2}
    for name, score in sorted(scores.items(), key=lambda kv: kv[1]):
        print(name, score)
    print("--- desc")
    for name, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        print(name, score)
    print("--- by name length")
    ranked = sorted(scores.items(), key=lambda kv: len(kv[0]))
    print(ranked)
    best = max(scores.items(), key=lambda kv: kv[1])
    print(best)
    worst = min(scores, key=lambda k: scores[k])
    print(worst)
    print(sorted(scores.items())[0])
    print(len(scores))
    print(scores)


main()
