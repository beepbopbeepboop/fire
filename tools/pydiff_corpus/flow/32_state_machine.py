def step(state: str, token: str) -> str:
    if state == "start":
        if token == "go":
            return "running"
        elif token == "stop":
            return "start"
        else:
            return "error"
    elif state == "running":
        if token == "stop":
            return "halted"
        elif token == "go":
            return "running"
        else:
            return "error"
    elif state == "halted":
        return "halted"
    else:
        return "unknown"


def run(tokens: list) -> str:
    state = "start"
    for t in tokens:
        state = step(state, t)
        if state == "error":
            break
    return state


def main():
    print(run(["go", "go", "stop"]))
    print(run(["stop"]))
    print(run(["go", "jump", "stop"]))
    print(run(["go", "stop", "go", "stop"]))
    print(run([]))
    print(step("bogus", "go"))
    print(step("halted", ""))


main()
