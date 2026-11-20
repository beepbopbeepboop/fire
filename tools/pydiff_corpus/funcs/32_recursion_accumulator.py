def digits(n, acc):
    if n < 10:
        acc.append(n)
        return acc
    acc.append(n % 10)
    return digits(n // 10, acc)


def sum_to(n, acc=0):
    if n == 0:
        return acc
    return sum_to(n - 1, acc + n)


def flatten(items, acc):
    for x in items:
        if isinstance(x, list):
            flatten(x, acc)
        else:
            acc.append(x)
    return acc


def main():
    print(digits(1234, []))
    print(digits(0, []))
    print(digits(7, []))
    print(digits(100, []))
    print(sum_to(4))
    print(sum_to(0))
    print(flatten([1, [2, [3, "a"]], [], None], []))
    print(flatten([], [9]))
    shared = []
    digits(5, shared)
    digits(6, shared)
    print(shared)
    print(digits(10, []) == digits(10, []))


main()
