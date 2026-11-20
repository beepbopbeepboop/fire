def total(*nums):
    s = 0
    for n in nums:
        s += n
    return s

def show(first, *rest):
    print(first, len(rest), list(rest))

def main():
    print(total())
    print(total(5))
    print(total(1, 2, 3))
    show("a")
    show("a", "b", "c")
    args = [1, 2, 3]
    print(total(*args))
main()
