def label(value=None):
    if value is None:
        return "missing"
    if value == 0:
        return "zero"
    return "value"

def main():
    print(label())
    print(label(None))
    print(label(0))
    print(label(-1))
    print(0 == None)
    print(None == None)
    n = 0
    print(n is None)
    print([0, 1, 2][0])
    lst = [0, 1]
    print(lst)
    print(None in [0, 1])
    print(0 in [None, 1])
main()
