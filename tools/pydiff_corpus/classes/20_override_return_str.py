class Employee:
    def __init__(self, name, level):
        self.name = name
        self.level = level

    def title(self):
        return "staff"

    def badge(self):
        return "[" + self.title() + "] " + self.name


class Manager(Employee):
    def title(self):
        return "manager"


class Intern(Employee):
    def title(self):
        return ""

    def badge(self):
        return "(intern) " + self.name


def main():
    staff = [Employee("ann", 1), Manager("bo", 3), Intern("", 0)]
    for e in staff:
        print(e.title())
    for e in staff:
        print(e.badge())
    titles = [e.title() for e in staff]
    print(titles)
    print(titles[2] == "")
    print(len(titles[2]))
    print(staff[1].level)
    print(staff[2].level)
    print(staff[1].title().upper())
    print(type(staff[2].title()).__name__)


main()
