def main():
    words = ["pear", "Apple", "fig", "banana", ""]
    print(sorted(words))
    words.sort()
    print(words)
    print(sorted(words, reverse=True))
    print(sorted([3, 1, 2]))
main()
