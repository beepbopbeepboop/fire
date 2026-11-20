def main():
    inventory = {"apple": 3, "pear": 0, "fig": ""}
    print(len(inventory))
    print("pear" in inventory)
    print(0 in inventory)
    print(3 in inventory)
    print(3 in inventory.values())
    print("" in inventory.values())
    print("fig" in inventory.keys())
    print(("apple", 3) in inventory.items())
    print(None in inventory)
    inventory[None] = "nothing"
    print(None in inventory, len(inventory))
    inventory["apple"] = 0
    print(len(inventory))
    print(0 in inventory.values())
    print(inventory.get(None))
    print("pear" not in inventory)
    inventory["kiwi"] = None
    print(len(inventory), inventory["kiwi"] is None)
    print(sorted(str(k) for k in inventory))
    print(sum(1 for v in inventory.values() if not v))


main()
