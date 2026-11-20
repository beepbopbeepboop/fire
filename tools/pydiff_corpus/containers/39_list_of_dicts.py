def main():
    people = [
        {"name": "ann", "age": 31, "tags": []},
        {"name": "", "age": 0, "tags": ["new"]},
        {"name": "cy", "age": -1, "tags": None},
    ]
    print(len(people))
    print(people[0]["name"])
    print(people[1]["age"])
    print(people[-1]["age"])
    print(people[1]["tags"])
    print(people[0].get("nick", "none"))
    print(people[0].get("age", 0) or "falsy")
    print(people[1].get("age") or "falsy")
    names = [p["name"] for p in people]
    print(names)
    print([p["name"] for p in people if p["name"]])
    people[0]["tags"].append("admin")
    print(people[0]["tags"])
    print(people[2]["tags"] is None)
    ages = sorted(p["age"] for p in people)
    print(ages)
    people.sort(key=lambda p: p["age"])
    print([p["name"] for p in people])
    print(sum(p["age"] for p in people))


main()
