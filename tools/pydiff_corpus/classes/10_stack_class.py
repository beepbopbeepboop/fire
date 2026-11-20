class Stack:
    def __init__(self):
        self.items = []

    def push(self, item):
        self.items.append(item)

    def pop(self):
        if self.is_empty():
            return None
        return self.items.pop()

    def peek(self):
        if self.is_empty():
            return None
        return self.items[-1]

    def is_empty(self):
        return len(self.items) == 0


def main():
    s = Stack()
    print(s.is_empty())
    print(s.pop())
    print(s.peek())
    s.push(1)
    s.push("two")
    s.push(None)
    s.push(False)
    print(s.peek())
    print(s.pop())
    print(s.pop())
    print(s.pop())
    print(s.items)
    s.push(0)
    print(s.pop())
    print(s.pop())
    print(s.is_empty())


main()
