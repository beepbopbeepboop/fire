"""Regression: erased bytes misclassified as string (type-erased param
handled by mojo_boxed_is_str / mojo_iter_boxed_list / _mojo_generic_elem_repr)."""

def main():
    # Unannotated parameter => type-erased handle; must agree with static path.
    def f(x):
        print(list(x))

    def g(x):
        print(x)

    f(b"cd")
    g(b"cd")
