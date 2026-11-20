class Item:
    def __init__(self, name: str, price: int, in_stock: bool):
        self.name = name
        self.price = price
        self.in_stock = in_stock

    def label(self):
        status = "yes" if self.in_stock else "no"
        return self.name + " " + str(self.price) + " " + status


def main():
    items = [
        Item("pen", 3, True),
        Item("cup", 0, False),
        Item("", -1, True),
        Item("lamp", 40, True),
    ]
    for it in items:
        print(it.label())
    total = 0
    for it in items:
        if it.in_stock:
            total += it.price
    print(total)
    names = []
    for it in items:
        names.append(it.name)
    print(names)
    print(len(items))
    print(items[1].name)
    print(items[-1].price)
    in_stock = [it.name for it in items if it.in_stock]
    print(in_stock)
    items[0].price = 10
    print(items[0].label())
    print(items[0] is items[0])


main()
