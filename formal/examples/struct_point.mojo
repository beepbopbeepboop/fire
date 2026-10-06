# A struct with two fields, constructed and read back: the construction is one
# store pair and the read is a field offset, which is the smallest object the
# formal path can hold.
struct Point:
    x: Int
    y: Int


def struct_point(n):
    p = Point()
    p.x = n
    p.y = n + 1
    return p.x + p.y
