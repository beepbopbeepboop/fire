def main():
    people = [("bo", 25), ("al", 30), ("cy", 25), ("di", 30), ("ed", 20)]
    print(sorted(people, key=lambda p: p[1]))
    print(sorted(people, key=lambda p: (-p[1], p[0])))
    by_name = sorted(people, key=lambda p: p[0])
    print(sorted(by_name, key=lambda p: p[1], reverse=True))
    work = people[:]
    work.sort(key=lambda p: p[0])
    work.sort(key=lambda p: p[1])
    print(work)
    print(max(people, key=lambda p: p[1]))
    print(min(people, key=lambda p: (p[1], p[0])))
    print(sorted([("x", 0), ("a", 0)], key=lambda p: p[1]))
    print(people)


main()
