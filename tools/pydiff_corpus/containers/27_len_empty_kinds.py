def main():
    empty_list = []
    empty_tuple = ()
    empty_dict = {}
    empty_set = set()
    empty_str = ""
    print(len(empty_list), len(empty_tuple), len(empty_dict), len(empty_set), len(empty_str))
    one = [None]
    print(len(one))
    print(len([[]]))
    print(len([[], []]))
    print(len({"": ""}))
    print(len((None,)))
    print(len(" "))
    print(len("ab" * 3))
    print(len(list(range(0))))
    print(len(range(5, 2)))
    print(len(dict.fromkeys([0, "", None])))
    print(len(list("")))
    print(len([0, False, ""]))
    print(bool(empty_tuple), bool(empty_set), bool(empty_str), bool(one))


main()
