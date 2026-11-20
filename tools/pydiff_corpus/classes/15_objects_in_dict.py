class Player:
    def __init__(self, name, score):
        self.name = name
        self.score = score

    def win(self, points=10):
        self.score += points
        return self.score


def main():
    players = {}
    players["ann"] = Player("ann", 5)
    players["bob"] = Player("bob", 0)
    players["cy"] = Player("", -3)
    print(len(players))
    print(players["ann"].score)
    print(players["bob"].name == "bob")
    print(players["cy"].name == "")
    print(players["ann"].win())
    print(players["ann"].win(-20))
    print("dan" in players)
    print("bob" in players)
    players["bob"].win(1)
    print(players["bob"].score)
    total = 0
    for key in sorted(players.keys()):
        total += players[key].score
        print(key, players[key].score)
    print(total)
    alias = players["cy"]
    alias.score = 99
    print(players["cy"].score)
    print(players.get("zed") is None)


main()
