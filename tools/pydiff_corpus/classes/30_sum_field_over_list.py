class Expense:
    def __init__(self, label: str, amount: int):
        self.label = label
        self.amount = amount


class Report:
    def __init__(self):
        self.expenses = []

    def add(self, label, amount):
        self.expenses.append(Expense(label, amount))

    def total(self) -> int:
        result = 0
        for e in self.expenses:
            result += e.amount
        return result


def main():
    r = Report()
    print(r.total())
    r.add("food", 25)
    r.add("rent", 900)
    r.add("gift", -15)
    r.add("", 0)
    print(r.total())
    print(len(r.expenses))
    print(r.expenses[2].amount)
    q = Report()
    q.add("only", -4)
    print(q.total())
    print(r.total() - q.total())
    print(r.expenses[3].label == "")


main()
