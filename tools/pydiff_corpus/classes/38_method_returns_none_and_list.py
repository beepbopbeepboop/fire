class Inventory:
    def __init__(self):
        self.stock = {}

    def add(self, name: str, qty: int):
        self.stock[name] = self.stock.get(name, 0) + qty

    def remove(self, name: str, qty: int):
        if name not in self.stock or self.stock[name] < qty:
            return None
        self.stock[name] -= qty
        return self.stock[name]

    def names(self):
        return sorted(self.stock.keys())


def main():
    inv = Inventory()
    r = inv.add("bolt", 5)
    print(r is None)
    print(r)
    print(inv.remove("bolt", 2))
    print(inv.remove("bolt", 10) is None)
    print(inv.remove("nut", 1) is None)
    inv.add("", 0)
    print(inv.names())
    print(inv.stock)
    print(inv.remove("bolt", 3))
    print(inv.stock["bolt"])
    print(inv.remove("", 0))
    results = [inv.add("gear", i) for i in range(2)]
    print(results)
    print(inv.names())
    print(inv.stock["gear"])


main()
