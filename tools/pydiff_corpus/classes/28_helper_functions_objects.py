class Task:
    def __init__(self, title: str, done: bool, hours: int):
        self.title = title
        self.done = done
        self.hours = hours


def count_done(tasks):
    n = 0
    for t in tasks:
        if t.done:
            n += 1
    return n


def total_hours(tasks) -> int:
    return sum([t.hours for t in tasks])


def find(tasks, title):
    for t in tasks:
        if t.title == title:
            return t
    return None


def main():
    tasks = [
        Task("write", True, 3),
        Task("test", False, 2),
        Task("", False, 0),
        Task("ship it now", True, -1),
    ]
    print(count_done(tasks))
    print(count_done([]))
    print(total_hours(tasks))
    print(total_hours([]))
    print(find(tasks, "test").hours)
    print(find(tasks, "nope") is None)
    print(find(tasks, "") is tasks[2])
    print(count_done(tasks[:2]))


main()
