# A struct with a METHOD, called on a constructed value. The receiver is a
# frame-shaped argument bound to the method's first parameter, so this covers
# the method-call rewrite and the receiver binding together. The method is
# declared INSIDE the struct body, which is the only spelling the receiver
# rewrite recognises.
struct Counter:
    v: Int

    def bump(self, k):
        return self.v + k


def struct_method(n):
    c = Counter()
    c.v = n
    return c.bump(5)
