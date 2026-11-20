class Account:
    def __init__(self, owner: str, balance: int):
        self.owner = owner
        self.balance = balance

    def get_owner(self) -> str:
        return self.owner

    def get_balance(self) -> int:
        return self.balance

    def is_empty(self) -> bool:
        return self.balance == 0

    def is_negative(self) -> bool:
        return self.balance < 0

    def doubled(self):
        return self.balance * 2

    def label(self):
        return "[" + self.owner + "]"


def main():
    a = Account("ann", 50)
    print(a.get_owner())
    print(a.get_balance())
    print(a.is_empty())
    print(a.is_negative())
    print(a.doubled())
    print(a.label())
    b = Account("", 0)
    print(b.get_owner() == "")
    print(b.is_empty())
    print(b.is_negative())
    print(b.doubled())
    print(b.label())
    c = Account("cy", -7)
    print(c.is_negative())
    print(c.doubled())
    print(c.is_empty())


main()
