class Counter:
    def __init__(self, start=0):
        self.value = start
        self.history = []

    def increment(self, by=1):
        self.value += by
        self.history.append(self.value)
        return self.value

    def decrement(self, by=1):
        self.value -= by
        self.history.append(self.value)
        return self.value

    def reset(self):
        self.value = 0
        return self.history


def main():
    c = Counter()
    print(c.value)
    print(c.increment())
    print(c.increment(5))
    print(c.decrement(2))
    print(c.decrement(-3))
    print(c.history)
    d = Counter(-4)
    print(d.value)
    print(d.increment(0))
    print(d.history)
    print(c.value)
    print(c.reset())
    print(c.value)
    print(d.value)


main()
