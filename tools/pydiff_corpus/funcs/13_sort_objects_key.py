class Item:
    def __init__(self, name, weight):
        self.name = name
        self.weight = weight


def names(items):
    return [it.name for it in items]


def main():
    items = [
        Item("crate", 12),
        Item("bag", 3),
        Item("anvil", 40),
        Item("box", 3),
        Item("", 0),
    ]
    print(names(sorted(items, key=lambda it: it.weight)))
    print(names(sorted(items, key=lambda it: it.name)))
    print(names(sorted(items, key=lambda it: (it.weight, it.name))))
    print(names(sorted(items, key=lambda it: it.weight, reverse=True)))
    items.sort(key=lambda it: len(it.name))
    print(names(items))
    print(sum(it.weight for it in items))
    heaviest = max(items, key=lambda it: it.weight)
    print(heaviest.name)
    print(min(items, key=lambda it: it.name).weight)


main()
