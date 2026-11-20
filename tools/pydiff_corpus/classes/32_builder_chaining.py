class QueryBuilder:
    def __init__(self):
        self.table = ""
        self.conditions = []
        self.limit = None

    def from_table(self, name):
        self.table = name
        return self

    def where(self, cond):
        self.conditions.append(cond)
        return self

    def take(self, n=10):
        self.limit = n
        return self

    def build(self) -> str:
        text = "SELECT * FROM " + self.table
        if len(self.conditions) > 0:
            text = text + " WHERE " + " AND ".join(self.conditions)
        if self.limit is not None:
            text = text + " LIMIT " + str(self.limit)
        return text


def main():
    q = QueryBuilder().from_table("users")
    print(q.build())
    q.where("age > 3").where("name != ''")
    print(q.build())
    q.take()
    print(q.build())
    q2 = QueryBuilder().from_table("t").take(0)
    print(q2.build())
    print(q2.limit is None)
    print(q2.take(5) is q2)
    print(QueryBuilder().build())
    print(QueryBuilder().limit is None)
    print(q.conditions)


main()
