def classify(n: int) -> str:
    if n == 0:
        return "zero"
    if n < 0:
        return "negative"
    if n % 2 == 0:
        return "even"
    if n > 100:
        return "big odd"
    return "odd"


def first_negative(items):
    for i in range(len(items)):
        if items[i] < 0:
            return i
    return -1


def main():
    print(classify(0))
    print(classify(-8))
    print(classify(-1))
    print(classify(4))
    print(classify(7))
    print(classify(101))
    print(classify(102))
    print(first_negative([]))
    print(first_negative([3, 0, -2, -9]))
    print(first_negative([1, 2]))


main()
