def main():
    result = None
    print(result)
    print(result is None)
    result = [1, 2]
    print(result)
    result.append(None)
    print(result)
    print(len(result))
    print(result[-1] is None)
    result = None
    print(result or "reset to default")
    result = []
    print(result, result or "empty list is falsy")
    maybe = [None]
    print(maybe[0] or "inner none")
    print(maybe[0] is None and maybe != [])
    cache = None
    for i in range(3):
        if cache is None:
            cache = [i]
        else:
            cache = cache + [i]
    print(cache)


main()
