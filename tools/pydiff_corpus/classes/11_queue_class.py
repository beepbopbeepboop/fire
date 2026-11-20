class Queue:
    def __init__(self):
        self.items = []

    def enqueue(self, item):
        self.items.append(item)

    def dequeue(self):
        if len(self.items) == 0:
            return "<empty>"
        return self.items.pop(0)

    def front(self):
        if len(self.items) == 0:
            return None
        return self.items[0]

    def size(self):
        return len(self.items)


def main():
    q = Queue()
    print(q.dequeue())
    print(q.front())
    q.enqueue("a")
    q.enqueue(2)
    q.enqueue("")
    print(q.size())
    print(q.front())
    print(q.dequeue())
    print(q.dequeue())
    print(q.items)
    print(q.dequeue())
    print(q.dequeue())
    print(q.size())
    r = Queue()
    r.enqueue(-1)
    print(r.front())
    print(q.size() == r.size())


main()
