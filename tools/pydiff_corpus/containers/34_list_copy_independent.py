def main():
    original = [1, [2, 3], "s"]
    by_list = list(original)
    by_slice = original[:]
    by_copy_method = original.copy()
    original[0] = 100
    print(original)
    print(by_list)
    print(by_slice[0])
    print(by_copy_method[0])
    original.append("new")
    print(len(original), len(by_list))
    original[1].append(4)
    print(by_list[1])
    print(by_slice[1] is original[1])
    by_list.append(None)
    print(by_list[-1], len(by_slice))
    flat = [0, 1]
    alias = flat
    alias[0] = 7
    print(flat)
    print(alias is flat)
    deep = [row[:] for row in [[1], [2]]]
    print(deep)
    d = {"k": [1]}
    dcopy = dict(d)
    dcopy["k"].append(2)
    print(d)
    print(dcopy == d)


main()
