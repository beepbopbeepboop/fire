def push(item, bucket=[]):
    bucket.append(item)
    return len(bucket)


def main():
    print(push(1))
    print(push(2))
    print(push(3, []))
    print(push(4))
    print(push("five"))
    print(push(None))
    fresh = []
    print(push(7, fresh))
    print(push(8, fresh))
    print(len(fresh))
    print(push(9))


main()
