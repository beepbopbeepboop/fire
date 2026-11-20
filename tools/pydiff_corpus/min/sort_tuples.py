def main():
    pairs = [("bob", 3), ("al", 3), ("cy", 1), ("al", 0)]
    print(sorted(pairs))
    print(sorted(pairs, key=lambda p: p[1]))
    pairs.sort(key=lambda p: p[0])
    print(pairs)
main()
