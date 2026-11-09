from . import other


def consume() -> Int:
    return other.shared_fn()
