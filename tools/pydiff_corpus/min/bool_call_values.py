def is_pos(n):
    return n > 0

def main():
    b = [is_pos(1), is_pos(-2)]
    print(b)
    g = (True, is_pos(0))
    print(g)
    h = {"k": is_pos(3)}
    print(h)
    t = [is_pos(1)]
    print(t[0], t)
    print([is_pos(i) for i in range(-1, 2)])
main()
