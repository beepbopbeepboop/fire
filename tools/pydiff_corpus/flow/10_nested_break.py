def pairs_until_sum(limit: int) -> list:
    found = []
    for a in range(1, 5):
        for b in range(1, 5):
            if b > a:
                break
            if a + b > limit:
                break
            found.append((a, b))
        print("row", a, "done with", len(found))
    return found


def main():
    result = pairs_until_sum(4)
    print(result)
    print(len(result))
    print(pairs_until_sum(100)[-1])
    hits = 0
    for i in range(3):
        for j in range(3):
            if j == 1:
                break
            hits += 1
    print("hits", hits)
    print("i ended", i, "j ended", j)
    print(pairs_until_sum(0))


main()
