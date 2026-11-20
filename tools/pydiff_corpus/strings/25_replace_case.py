def main():
    s: str = "the cat sat"
    print(s.replace("at", "og"))
    print(s.replace("cat", ""))
    print(s.replace("x", "y"))
    print("aaaa".replace("aa", "b"))
    print("aaa".replace("a", "aa", 2))
    print("".replace("", "-"))
    print("abc".replace("", "-"))
    print(s.upper())
    print("MiXed".lower())
    print("hello world".title())
    print("hello WORLD".capitalize())
    print("".capitalize() == "")
    print("abc1 def".title())
    print("it's a dog's".title())


main()
