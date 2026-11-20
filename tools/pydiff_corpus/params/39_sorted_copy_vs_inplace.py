def sorted_copy(items):
    return sorted(items)


def sort_in_place(items):
    items.sort()


def sort_and_return(items):
    return items.sort()


def main():
    data = [3, -1, 2]
    s = sorted_copy(data)
    print(data)
    print(s)
    sort_in_place(data)
    print(data)
    r = sort_and_return([2, 1])
    print(r is None)
    print(sorted_copy([]))
    print(sorted_copy(["b", "a", ""]))
    words = ["pear", "Apple", "fig"]
    print(sorted_copy(words))
    print(words)
    print(sorted_copy([0, -0, 0.0]) == [0, 0, 0])
    print(len(sorted_copy([5, 5, 5])))


main()
