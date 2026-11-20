class Log:
    def __init__(self):
        self.entries = []

    def add(self, entry):
        self.entries.append(entry)
        return len(self.entries)

    def last(self):
        if len(self.entries) == 0:
            return None
        return self.entries[-1]

    def count_strings(self):
        n = 0
        for item in self.entries:
            if isinstance(item, str):
                n += 1
        return n


def main():
    log = Log()
    print(len(log.entries))
    print(log.last())
    print(log.add(1))
    print(log.add("two"))
    print(log.add(3))
    print(log.add(""))
    print(log.entries)
    print(log.last())
    print(log.count_strings())
    other = Log()
    print(other.entries)
    other.add("solo")
    print(other.entries)
    print(log.entries)


main()
