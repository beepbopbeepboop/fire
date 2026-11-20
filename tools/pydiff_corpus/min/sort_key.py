def main():
    words = ["pear", "Apple", "fig", "banana", ""]
    print(sorted(words, key=len))
    print(sorted(words, key=lambda w: w.lower()))
    nums = [3, -7, 2, 0, -1]
    print(sorted(nums, key=abs))
    print(sorted(nums, key=lambda n: -n))
main()
