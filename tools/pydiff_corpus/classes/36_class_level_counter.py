class Widget:
    created = 0

    def __init__(self, label: str):
        self.label = label
        Widget.created += 1
        self.serial = Widget.created

    def describe(self):
        return self.label + "#" + str(self.serial)


class Gadget(Widget):
    pass


def main():
    print(Widget.created)
    w1 = Widget("a")
    w2 = Widget("")
    print(Widget.created)
    print(w1.serial)
    print(w2.serial)
    print(w2.describe())
    g = Gadget("g")
    print(Widget.created)
    print(g.serial)
    print(g.describe())
    print(Gadget.created)
    print(w1.created)
    w1.created = 100
    print(Widget.created)
    print(w1.created)
    print(w2.created)
    items = [Widget(str(i)) for i in range(3)]
    print(items[-1].describe())
    print(Widget.created)


main()
