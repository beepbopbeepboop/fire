class C:
    def __init__(self):
        self.s = None
    def open(self, x):
        self.s = x
    def take(self):
        r = self.s
        self.s = None
        return r
c = C()
c.open(42)
print(c.take())
print(c.take())
