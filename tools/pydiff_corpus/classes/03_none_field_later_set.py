class Connection:
    def __init__(self, name):
        self.name = name
        self.session = None
        self.retries = 0

    def is_open(self):
        return self.session is not None

    def open(self, session_id):
        if self.session is None:
            self.session = session_id
            return True
        return False

    def close(self):
        result = self.session
        self.session = None
        return result


def main():
    c = Connection("db")
    print(c.is_open())
    print(c.session is None)
    print(c.open(42))
    print(c.is_open())
    print(c.open(99))
    print(c.session)
    print(c.close())
    print(c.session is None)
    print(c.close())
    print(c.is_open())
    d = Connection("cache")
    print(d.name)
    print(d.session)
    print(d.retries)


main()
