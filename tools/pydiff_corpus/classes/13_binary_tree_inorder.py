class TreeNode:
    def __init__(self, key):
        self.key = key
        self.left = None
        self.right = None


class BinaryTree:
    def __init__(self):
        self.root = None

    def insert(self, key):
        self.root = self._insert(self.root, key)

    def _insert(self, node, key):
        if node is None:
            return TreeNode(key)
        if key < node.key:
            node.left = self._insert(node.left, key)
        else:
            node.right = self._insert(node.right, key)
        return node

    def in_order(self):
        return self._walk(self.root)

    def _walk(self, node):
        if node is None:
            return []
        return self._walk(node.left) + [node.key] + self._walk(node.right)


def main():
    t = BinaryTree()
    print(t.in_order())
    for k in [5, 3, 8, 1, 4, 8, -2, 0]:
        t.insert(k)
    print(t.in_order())
    print(t.root.key)
    print(t.root.left.key)
    print(t.root.right.right.key)


main()
