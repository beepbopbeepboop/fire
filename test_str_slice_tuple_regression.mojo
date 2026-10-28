from std.collections.string import StringSlice

def get_sign(x: StringSlice[_]) -> Tuple[Float64, type_of(x)]:
    if x[byte=0] == "-":
        return (-1.0, x[byte=1:])
    return (1.0, x)

def main():
    var s = get_sign("-abc")
    print(s[0])
