class Node:
    def __init__(self, label, children=None):
        self.label = label
        if children is None:
            children = []
        self.children = children

    def depth(self) -> int:
        best = 0
        for c in self.children:
            d = c.depth()
            if d > best:
                best = d
        return best + 1

    def count(self) -> int:
        total = 1
        for c in self.children:
            total += c.count()
        return total


def main():
    leaf = Node("leaf")
    print(leaf.depth())
    print(leaf.count())
    root = Node("root", [Node("a", [Node("a1"), Node("a2")]), Node("b"), Node("")])
    print(root.depth())
    print(root.count())
    print(root.children[0].children[1].label)
    print(len(root.children[1].children))
    print(Node("x").depth() - leaf.depth())


main()
