def describe(**kwargs):
    print(len(kwargs))
    for k, v in sorted(kwargs.items()):
        print(k, v)


def keys_of(**kwargs):
    return sorted(kwargs.items())


def main():
    describe()
    describe(b=2, a=1)
    describe(x=None, y=False, z="")
    describe(nested={"k": 0}, count=-1)
    print(keys_of(q=1, p=2))
    print(keys_of())
    print(keys_of(zz=0, a=0))
    extra = {"m": 5, "n": None}
    describe(**extra)
    describe(**extra, o=[])
    print(keys_of(a=[]))
    print(len(keys_of(**extra)))


main()
