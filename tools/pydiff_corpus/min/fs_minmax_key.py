def main():
    print(max(["a", "bb", "c"], key=len))
    print(min(["aaa", "bb", "cc"], key=len))
    print(max([3, -7, 2], key=abs))
    print(min([3, -7, 2], key=lambda n: -n))
    print(max([1, 5, 2]))
main()
def more():
    print(max([1.5, -2.5, 0.5], key=abs))
    print(min([1.5, -2.5, 0.5], key=abs))
more()
