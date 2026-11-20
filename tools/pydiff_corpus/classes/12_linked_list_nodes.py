class Node:
    def __init__(self, value, next_node=None):
        self.value = value
        self.next = next_node


class LinkedList:
    def __init__(self):
        self.head = None

    def push_front(self, value):
        self.head = Node(value, self.head)

    def to_list(self):
        out = []
        cur = self.head
        while cur is not None:
            out.append(cur.value)
            cur = cur.next
        return out

    def last_value(self):
        if self.head is None:
            return None
        cur = self.head
        while cur.next is not None:
            cur = cur.next
        return cur.value


def main():
    ll = LinkedList()
    print(ll.head is None)
    print(ll.to_list())
    print(ll.last_value())
    ll.push_front(3)
    ll.push_front("two")
    ll.push_front(0)
    print(ll.to_list())
    print(ll.last_value())
    print(ll.head.next.value)
    print(ll.head.next.next.next is None)


main()
