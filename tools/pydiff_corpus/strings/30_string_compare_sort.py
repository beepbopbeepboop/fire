def main():
    words = ["pear", "Apple", "banana", "apple", "", "Zebra", "10", "9"]
    print(sorted(words))
    print(sorted(words, key=str.lower))
    print(sorted(words, key=len))
    print(sorted(words, reverse=True))
    print("a" < "b")
    print("abc" < "abd")
    print("ab" < "abc")
    print("" < "a")
    print("Z" < "a")
    print("10" < "9")
    print("apple" == "apple")
    print("apple" != "Apple")
    print(max(words))
    print(min(words))
    print(sorted(["b", "a", "b"]))


main()
