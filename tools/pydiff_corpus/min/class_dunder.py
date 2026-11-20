class P:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def __eq__(self, other):
        return self.x == other.x and self.y == other.y
    def __len__(self):
        return self.x
    def __contains__(self, v):
        return v == self.x or v == self.y
    def __getitem__(self, i):
        return self.x if i == 0 else self.y
    def __str__(self):
        return "P(" + str(self.x) + ", " + str(self.y) + ")"

def main():
    a = P(1, 2)
    b = P(1, 2)
    print(a == b)
    print(a is b)
    print(len(a))
    print(2 in a)
    print(5 in a)
    print(a[0], a[1])
    print(a)
    print(str(a))
    print(isinstance(a, P))
main()
