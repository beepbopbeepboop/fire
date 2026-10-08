def g():
    yield 1
    yield 2

def main():
    for x in g():
        print(x)
