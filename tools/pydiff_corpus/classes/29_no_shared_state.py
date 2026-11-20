class Basket:
    def __init__(self, owner: str):
        self.owner = owner
        self.items = []
        self.limits = {"max": 3}
        self.paid = False

    def add(self, item):
        if len(self.items) < self.limits["max"]:
            self.items.append(item)
            return True
        return False


def main():
    a = Basket("ann")
    b = Basket("bob")
    a.add("apple")
    a.add("pear")
    b.add("fig")
    print(a.items)
    print(b.items)
    print(len(a.items))
    print(len(b.items))
    a.limits["max"] = 1
    print(b.limits["max"])
    print(a.add("plum"))
    print(b.add("kiwi"))
    print(b.items)
    a.paid = True
    print(b.paid)
    print(a.owner)
    print(b.owner)
    print(a.items is b.items)
    c = Basket("cy")
    print(c.items)
    print(c.limits["max"])
    print(a.items == b.items)


main()
