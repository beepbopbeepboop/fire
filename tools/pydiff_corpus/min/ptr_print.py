def pair():
    return ("a", "b")

def main():
    print(pair())
    t = (-3.5, 3)
    print(t)
    d = {"ann": 3, "bo": 0}
    print(list(d.items()))
    print([(i, c) for i, c in enumerate("hi")])
    print([[1, 2], [3, [4, []]]])
main()
