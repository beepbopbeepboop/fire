def main():
    items = [0, 1, "", "x", None, [], [0], 0.0, -2, False, True]
    truthy = 0
    falsy = 0
    for item in items:
        if item:
            truthy += 1
        else:
            falsy += 1
    print("truthy", truthy)
    print("falsy", falsy)
    best = None
    for item in items:
        best = best or item
    print("first truthy via or:", best)
    chain = 1
    for item in items:
        chain = chain and item
    print("chain via and:", chain)
    flags = []
    for item in items[:4]:
        flags.append(not item)
    print(flags)
    print(sum(1 for x in items if x is None))
    print(sum(1 for x in items if x == 0))
    print(sum(1 for x in items if x == False))
    print(items.index(None))
    print(items.count(0))
    print(items.count(False))


main()
